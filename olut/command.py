#!/usr/bin/env python

import datetime
import logging
import os
import re
import subprocess
import sys
import tarfile
import time
import yaml
from contextlib import closing
from optparse import OptionParser
from StringIO import StringIO

class Olut(object):
    DEFAULT_IGNORE_FILENAME_RE = re.compile(".*(\.py[co]|\.swp|~)$")
    DEFAULT_INSTALL_PATH = "/var/lib/olut"
    
    def __init__(self, install_path=None, ignore_filename_re=None):
        self.log = logging.getLogger("olut")
        self.install_path = install_path or os.getenv("OLUT_INSTALL_PATH") or self.DEFAULT_INSTALL_PATH
        self.ignore_filename_re = ignore_filename_re or os.getenv("OLUT_IGNORE_FILENAME_RE") or self.DEFAULT_IGNORE_FILENAME_RE
        if isinstance(self.ignore_filename_re, basestring):
            self.ignore_filename_re = re.compile(self.ignore_filename_re)

    def build(self, sourcepath, outpath=".", metapath="olut", metaoverride=None):
        if not os.path.exists(outpath):
            os.makedirs(outpath)
        
        sourcepath = sourcepath.rstrip('/')
        if not os.path.exists(sourcepath):
            raise IOError("Source path does not exist")
        
        # read & generate meta
        meta = self.get_git_meta(sourcepath)
        if not metapath.startswith('/'):
            metapath = os.path.join(sourcepath, metapath)
        metafile_path = os.path.join(metapath, "metadata.yaml")
        if os.path.exists(metafile_path):
            with open(metafile_path) as fp:
                projmeta = yaml.load(fp)
                if projmeta:
                    meta.update(progmeta)
        if metaoverride:
            meta.update(metaoverride)
        meta["build_date"] = datetime.datetime.now()
        
        # Build package tar.gz
        ignored_files = meta.pop('ignored_files', [])
        outname = "%s-%s.tgz" % (meta["name"], meta["version"])
        outpath = os.path.join(outpath, outname)
        with closing(tarfile.open(outpath, "w:gz")) as fp:
            for root, dirs, files in os.walk(sourcepath):
                # Skip ignored directories
                if ".git" in dirs:
                    dirs.remove(".git")
                for d in list(dirs):
                    if d in ignored_files or (d+"/") in ignored_files:
                        dirs.remove(d)

                pkgroot = root[len(sourcepath)+1:]
                #if pkgroot in ignored_files or (pkgroot+"/") in ignored_files:
                #    continue

                for f in files:
                    realpath = os.path.join(root, f)
                    pkgpath = os.path.join(pkgroot, f)
                    if self.ignore_filename_re.match(pkgpath):
                        continue
                    if pkgpath in ignored_files:
                        continue
                    
                    self.log.info(pkgpath)
                    fp.add(realpath, pkgpath)
            
            # Include files from the metadata/scripts path
            # except metadata.yaml which we deal with separately
            for root, dirs, files in os.walk(metapath):
                pkgroot = root[len(metapath)+1:]
                for f in files:
                    if self.ignore_filename_re.match(f):
                        continue
                    if f == "metadata.yaml":
                        continue
                    realpath = os.path.join(root, f)
                    pkgpath = os.path.join(".olut", pkgroot, f)
                    fp.add(realpath, pkgpath)
            
            # Write out modified metadata
            meta_yaml = yaml.dump(meta, default_flow_style=False)
            eti = fp.gettarinfo(sourcepath) # Use an existing file to get uid, gid, etc..
            ti = tarfile.TarInfo(".olut/metadata.yaml")
            ti.size = len(meta_yaml)
            ti.mtime = time.time()
            for k in ("uid", "gid", "uname", "gname"):
                setattr(ti, k, getattr(eti, k))
            fp.addfile(ti, StringIO(meta_yaml))
        return outpath

    def install(self, pkgpath):
        if not os.path.exists(self.install_path):
            os.makedirs(self.install_path)
        with closing(tarfile.open(pkgpath, "r")) as fp:
            meta = yaml.load(fp.extractfile(".olut/metadata.yaml"))
            meta["install_date"] = datetime.datetime.now()
            install_path = os.path.join(
                self.install_path,
                meta['name'],
                str(meta['version']),
            )
            os.makedirs(install_path)
            # Don't use fp.extractall as it doesn't check for filenames
            # starting with / or ..
            for name in fp.getnames():
                if name.startswith("..") or name.startswith("/"):
                    print "Ignoring invalid file", name
                    continue
                fp.extract(name, install_path)
        with open(os.path.join(install_path, ".olut/metadata.yaml"), "w") as fp:
            yaml.dump(meta, fp, default_flow_style=False)
        self.runscript(meta['name'], str(meta['version']), "install")
    
    def uninstall(self, pkg, ver):
        current_ver = self.get_current_version(pkg)
        if current_ver == ver:
            raise Exception("Can't uninstall the currently activated version. Must deactivate first.")
        pkg_path = os.path.join(self.install_path, pkg)
        if ver == "*":
            pass # TODO: Delete all versions
        else:
            pass # TODO: Delete given version

    def list(self):
        packages = self.get_installed_list()
        for name, info in packages.items():
            print name
            for version, meta in info["versions"]:
                scm = meta.get('scm', {})
                print "    {is_current} {version} branch:{branch} revision:{revision} tag:{tag}".format(
                    is_current = "@" if version == info["current"] else " ",
                    version = version,
                    branch = scm.get('branch', ''),
                    revision = scm.get('revision', '')[:8],
                    tag = scm.get('tag', ''),
                )
    
    def info(self, pkg):
        info = self.get_package_info(pkg)
        import pprint
        pprint.pprint(info)
    
    def activate(self, pkg, ver):
        current_path = os.path.join(self.install_path, pkg, "current")
        pkg_path = os.path.join(self.install_path, pkg, ver)
        if os.path.exists(current_path):
            raise Exception("Must deactivate current version first")
        os.symlink(pkg_path, current_path)
        self.runscript(pkg, ver, "activate") 

    def deactivate(self, pkg):
        current_path = os.path.join(self.install_path, pkg, "current")
        current_ver = self.get_current_version(pkg) 
        if not current_ver:
            print "No current version"
            return
        self.runscript(pkg, current_ver, "deactivate")
        if os.path.exists(current_path):
            os.unlink(current_path)

    def runscript(self, pkg, ver, script):
        version_path = os.path.join(self.install_path, pkg, ver)
        script_path = os.path.join(version_path, ".olut", script)
        if not os.path.exists(script_path):
            return
        env = dict(
            PKG_NAME = pkg,
            PKG_VERSION = ver,
            PKG_PATH = os.path.join(self.install_path, pkg),
            PKG_VERSION_PATH = version_path,
            PATH = os.environ["PATH"],
        )
        proc = subprocess.Popen([script_path], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out = proc.communicate()[0]
        if proc.returncode != 0:
            self.log.error(out)
            raise Exception("Script %s return a non-zero return code %d" % (script, proc.returncode))
        else:
            self.log.info(out)
    
    def get_git_ignored(self, path):
        p = subprocess.Popen("cd %s; git status --porcelain --ignored" % path, shell=True, stdout=subprocess.PIPE)
        out = p.communicate()[0]
        return [
            x.split(' ', 1)[1]
            for x in out.split("\n")
            if x.split(' ', 1)[0] == "!!"
        ]

    def get_git_meta(self, path):
        git_path = os.path.join(path, ".git")
        if not os.path.exists(git_path):
            return {}
        gitmeta = {"type": "git"}
        meta = {"scm": gitmeta}
        with open(os.path.join(git_path, "HEAD"), "rb") as fp:
            ref = fp.read().strip().split(" ")[-1]
            gitmeta["branch"] = ref.split('/')[-1]
        
        try:
            with open(os.path.join(git_path, ref), "r") as fp:
                revision = fp.read().strip()
        except IOError:
            # ref has probably been packed
            with open(os.path.join(git_path, "packed-refs"), "r") as fp:
                refs = fp.read().strip().split("\n")
            for r in refs:
                r = r.strip().split(' ')
                if r[-1] == ref:
                    revision = r[0]
                    break
        gitmeta["revision"] = revision
        
        tag = self.find_git_revision_tag(git_path, revision)
        if tag:
            gitmeta["tag"] = tag
            meta["version"] = "%s-%s" % (gitmeta["branch"], tag)
        else:
            meta["version"] = "%s-%s" % (
                gitmeta["branch"],
                datetime.datetime.now().strftime("%Y%m%dT%H%M%S"),
            )
         
        config = self.read_git_config(os.path.join(git_path, "config"))
        url = config.get("remote", {}).get("origin", {}).get("url")
        if url:
            gitmeta["url"] = url
            meta["name"] = url.rsplit('/', 1)[-1].rsplit('.', 1)[0]
        
        meta["ignored_files"] = self.get_git_ignored(path)

        return meta
    
    def find_git_revision_tag(self, path, revision):
        for tag in os.listdir(os.path.join(path, "refs/tags")):
            if tag.startswith('.'):
                continue
            with open(os.path.join(path, "refs/tags", tag), "r") as fp:
                rev = fp.read().strip()
            if rev == revision:
                return tag
    
    def read_git_config(self, path):
        config = {}
        section = None
        with open(path, "rb") as fp:
            for line in fp:
                line = line.strip()
                if line.startswith('['):
                    name = line[1:-1]
                    if " " in name:
                        name, sname = name.split(' ', 1)
                        sname = sname[1:-1]
                    else:
                        sname = None
                    section = config.setdefault(name, {})
                    if sname:
                        section = section.setdefault(sname, {})
                else:
                    key, value = line.split('=')
                    key = key.strip()
                    value = value.strip()
                    section[key] = value
        return config
    
    def get_package_info(self, path):
        with closing(tarfile.open(path, "r:gz")) as fp:
            meta = yaml.load(fp.extractfile(".olut/metadata.yaml"))
        return meta

    def get_installed_list(self):
        packages = dict((x, {})
            for x in os.listdir(self.install_path)
            if not x.startswith('.')
               and os.path.isdir(os.path.join(self.install_path, x)))
        for name in packages:
            packages[name]["versions"] = versions = []
            for ver in os.listdir(os.path.join(self.install_path, name)):
                ver_path = os.path.join(self.install_path, name, ver)
                if (ver.startswith('.')
                        or os.path.islink(ver_path)
                        or not os.path.exists(os.path.join(ver_path, ".olut"))):
                    continue
                with open(os.path.join(ver_path, ".olut", "metadata.yaml"), "r") as fp:
                    meta = yaml.load(fp)
                versions.append((ver, meta))
            versions.sort(key=lambda x:x[1]["install_date"], reverse=True)
            packages[name]["current"] = self.get_current_version(name)
        return packages
    
    def get_current_version(self, pkg):
        cur = os.path.realpath(
              os.path.join(self.install_path, pkg, "current")).rsplit('/')[-1]
        return cur if cur != "current" else None


def render_template(source, dest=None, pkg_ver_path=None):
    pkg_ver_path = pkg_ver_path or os.getenv("PKG_VERSION_PATH")
    if not pkg_ver_path or not os.path.exists(pkg_ver_path):
        sys.stderr.write("Must either pass in package version path or PKG_VERSION_PATH environment should be set\n")
        sys.exit(1)
    if not source.startswith('/'):
        source = os.path.join(pkg_ver_path, source)
    with open(os.path.join(pkg_ver_path, ".olut", "metadata.yaml"), "r") as fp:
        meta = yaml.load(fp)
    if not dest:
        if not source.endswith('.tmpl'):
            sys.stderr.write("When rendering a template either a destination must be provided or the source should end in '.tmpl'\n")
            sys.exit(1)
        dest = source.rsplit('.', 1)[0]
    if not dest.startswith('/'):
        dest = os.path.join(pkg_ver_path, dest)
    with open(source, "rb") as fp:
        meta["version_path"] = pkg_ver_path
        text = fp.read().format(**meta)
    with open(dest, "wb") as fp:
        fp.write(text)


def build_parser():
    parser = OptionParser(usage="Usage: %prog [options] <command> [arg1] [arg2]")
    parser.add_option("-m", "--meta", dest="meta", help="Additional meta data (name=value)", action="append")
    parser.add_option("-p", "--path", dest="path", help="Install path")
    parser.add_option("-v", "--verbose", dest="verbose", default=False, help="Verbose output", action="store_true")
    return parser


def main():
    parser = build_parser()
    options, args = parser.parse_args()
    try:
        command = args.pop(0)
    except IndexError:
        parser.error("must specify a command")
    if options.verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)
    olut = Olut(
        install_path = options.path,
    )
    kwargs = {}
    if command == "render":
        render_template(*args)
        sys.exit(0)
    if command == "build" and options.meta:
        kwargs["metaoverride"] = dict(
            x.split('=') for x in options.meta,
        )
    getattr(olut, command)(*args, **kwargs)

if __name__ == "__main__":
    main()
