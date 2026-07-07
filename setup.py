from setuptools import setup

setup(
    name='gigafile',
    version='3.3.0',
    description='A python module to download and upload from gigafile',
    author='Sraqzit, fireattack',
    install_requires=['requests>=2.25.1', 'requests_toolbelt>=0.9.1', 'tqdm>=4.61.2', 'beautifulsoup4>=4'],
    requires=[],
    packages=['gfile'],
    platforms=["Linux", "Mac OS-X", "Windows", "Unix"],
    entry_points={
        'console_scripts': [
           'gfile = gfile.cmd:main',
        ],
    },
)
