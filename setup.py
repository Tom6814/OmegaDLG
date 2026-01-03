from setuptools import setup

setup(
    name="omegadl",
    version="0.1.0",
    py_modules=["main"],
    python_requires=">=3.8",
    install_requires=["rich", "requests", "img2pdf", "beautifulsoup4"],
    entry_points={
        "console_scripts": [
            "omegadl=main:main",
        ]
    },
    description="A tiny cli to download omegascans manhwa",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Gaurav Raj",
    author_email="gauravraj0408@gmail.com",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GPLv3 License",
        "Operating System :: OS Independent",
    ],
    keywords="python manhwa omegascans",
    project_urls={
        "Bug Tracker": "https://github.com/thehackersbrain/omegadl/issues",
        "Source Code": "https://github.com/thehackersbrain/omegadl",
        "Credits": "https://github.com/thehackersbrain",
    },
)
