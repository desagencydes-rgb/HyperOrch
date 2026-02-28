from setuptools import setup, find_packages

setup(
    name="hyperorch",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "uvicorn[standard]>=0.28.0",
        "click>=8.1.0",
        "psutil>=5.9.0",
        "gputil>=1.4.0",
        "websockets>=12.0",
    ],
    entry_points={
        "console_scripts": [
            "hyperorch=hyperorch.cli:main",
        ],
    },
    python_requires=">=3.10",
)
