#!/usr/bin/env python

import os
import re
import subprocess
import sys
import tarfile
import yaml
from contextlib import closing
from optparse import OptionParser

class Olut(object):
    DEFAULT_IGNORE_FILENAME_RE = re.compile(".*(\.py[co]|\.swp|~)$")
    DEFAULT_INSTALL_PATH = "/var/olut"
    
    def __init__(self, install_path=None, ignore_filename_re=None):
        self.install_path = install_path or os.getenv("OLUT_INSTALL_PATH") or self.DEFAULT_INSTALL_PATH
        if not os.path.exists(self.install_path):
            os.makedirs(self.install_path)
        self.ignore_filename_re = ignore_filename_re or os.getenv("OLUT_IGNORE_FILENAME_RE") or self.DEFAULT_IGNORE_FILENAME_RE
        if isinstance(self.ignore_filename_re, basestring):
            self.ignore_filename_re = re.compile(self.ignore_filename_re)

    def build(self, sourcepath, outpath=".", metapath="olut"):
        if not metapath.startswith('/'):
            metapath = os.path.join(sourcepath, metapath)
        with open(os.path.join(metapath, "metadata.yaml")) as fp:
            meta = yaml.load(fp)
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
                    realpath = os.path.join(root, f)
                    pkgpath = os.path.join(".olut", pkgroot, f)
                    fp.add(realpath, pkgpath)

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
        )
        subprocess.check_call([script_path], env=env)

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
    parser.add_option("-p", "--path", dest="path", help="Install path")
    return parser

def main():
    parser = build_parser()
    options, args = parser.parse_args()
    try:
        command = args.pop(0)
    except IndexError:
        parser.error("must specify a command")
    olut = Olut(
        install_path = options.path,
    )
    getattr(olut, command)(*args)

if __name__ == "__main__":
    main()
