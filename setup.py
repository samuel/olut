#!/usr/bin/env python

from setuptools import setup, find_packages

import os
execfile(os.path.join('olut', 'version.py'))

setup(
    name = 'olut',
    version = VERSION,
    description = 'Olut is a packging framework meant for deploying applications',
    author = 'Samuel Stauffer',
    author_email = 'samuel@playhaven.com',
    url = 'https://github.com/playhaven/olut',
    packages = find_packages(),
    test_suite = "tests",
    entry_points = {
        "console_scripts": [
            "olut = olut.command:main",
        ],
    },
    classifiers = [
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    install_requires = ['pyyaml'],
)
