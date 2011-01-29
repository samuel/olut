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
    DEFAULT_INSTALL_PATH = "/var/olut"
    
    def __init__(self, install_path=None, ignore_filename_re=None):
        self.log = logging.getLogger("olut")
        self.install_path = install_path or os.getenv("OLUT_INSTALL_PATH") or self.DEFAULT_INSTALL_PATH
        if not os.path.exists(self.install_path):
            os.makedirs(self.install_path)
        self.ignore_filename_re = ignore_filename_re or os.getenv("OLUT_IGNORE_FILENAME_RE") or self.DEFAULT_IGNORE_FILENAME_RE
        if isinstance(self.ignore_filename_re, basestring):
            self.ignore_filename_re = re.compile(self.ignore_filename_re)

    def build(self, sourcepath, outpath=".", metapath="olut", metaoverride=None):
        meta = self.get_git_meta(sourcepath)
        if not metapath.startswith('/'):
            metapath = os.path.join(sourcepath, metapath)
        metafile_path = os.path.join(metapath, "metadata.yaml")
        if os.path.exists(metafile_path):
            with open(metafile_path) as fp:
                meta.update(yaml.load(fp))
        if metaoverride:
            meta.update(metaoverride)
        outname = "%s-%s.tgz" % (meta["name"], meta["version"])
        outpath = os.path.join(outpath, outname)
        with closing(tarfile.open(outpath, "w:gz")) as fp:
            for root, dirs, files in os.walk(sourcepath):
                if ".git" in dirs:
                    dirs.remove(".git")
                pkgroot = root[len(sourcepath)+1:]
                for f in files:
                    if self.ignore_filename_re.match(f):
                        continue
                    realpath = os.path.join(root, f)
                    pkgpath = os.path.join(pkgroot, f)
                    fp.add(realpath, pkgpath)
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
            meta_yaml = yaml.dump(meta, default_flow_style=False)
            eti = fp.gettarinfo(sourcepath)
            ti = tarfile.TarInfo(".olut/metadata.yaml")
            ti.size = len(meta_yaml)
            ti.mtime = time.time()
            for k in ("uid", "gid", "uname", "gname"):
                setattr(ti, k, getattr(eti, k))
            fp.addfile(ti, StringIO(meta_yaml))

    def install(self, pkgpath):
        with closing(tarfile.open(pkgpath, "r")) as fp:
            meta = yaml.load(fp.extractfile(".olut/metadata.yaml"))
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
        packages = self.get_package_list()
        for name, info in packages.items():
            print name, " ".join(("@"+v) if v == info["current"] else v for v in info["versions"])

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
    
    def get_git_meta(self, path):
        git_path = os.path.join(path, ".git")
        if not os.path.exists(git_path):
            return {}
        gitmeta = {}
        meta = {"git": gitmeta}
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
            meta["version"] = tag
        else:
            meta["version"] = datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + revision[:8]

        config = self.read_git_config(os.path.join(git_path, "config"))
        url = config.get("remote", {}).get("origin", {}).get("url")
        if url:
            gitmeta["url"] = url
            if url.endswith(".git"):
                meta["name"] = url.rsplit('/', 1)[-1].rsplit('.', 1)[0]

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

    def get_package_list(self):
        packages = dict((x, {})
            for x in os.listdir(self.install_path)
            if not x.startswith('.'))
        for name in packages:
            packages[name]["versions"] = [
                x for x in os.listdir(os.path.join(self.install_path, name))
                if not x.startswith('.') and x != "current"]
            packages[name]["current"] = cur = self.get_current_version(name)
        return packages

    def get_current_version(self, pkg):
        cur = os.path.realpath(
              os.path.join(self.install_path, pkg, "current")).rsplit('/')[-1]
        return cur if cur != "current" else None


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
    if command == "build" and options.meta:
        kwargs["metaoverride"] = dict(
            x.split('=') for x in options.meta,
        )
    getattr(olut, command)(*args, **kwargs)

if __name__ == "__main__":
    main()
