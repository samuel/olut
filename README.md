Olut
====

Packaging framework designed to ease the process of deployment.

Commands
--------

* **build** *source_path* [*destination_path*] [*path_to_olut_metadata*] - build a package
* **install** *package_path* - install a package
* **activate** *name* *version* - activate a specific version
* **deactivate** *name* - deactivate the current version

Package Scripts
---------------

Scripts receive the following environment variables:

* PKG_NAME
* PKG_VERSION
* PKG_PATH
* PKG_VERSION_PATH

Scripts run at various times:

* install
* activate
* deactivate

Version Matching
----------------

* * - all
* ~[re] - regex search
* HEAD - most recent
* HEAD- - one before the most recent
* CUR - current version
* CUR- - one before current
* CUR++ - two after current

