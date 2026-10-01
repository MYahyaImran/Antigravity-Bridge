from setuptools import setup, find_packages

setup(
    name="antigravity-bridge",
    version="1.0.2",
    description="Multi-account Google Antigravity bridge with zero-drop quota rotation and agent adapters",
    author="Antigravity Bridge Team",
    url="https://github.com/MYahyaImran/Antigravity-Bridge",
    packages=find_packages(),
    package_data={
        "": ["static/*"],
    },
    include_package_data=True,
    python_requires=">=3.9",
    install_requires=[
        "fastapi>=0.100.0",
        "uvicorn>=0.20.0",
        "httpx>=0.24.0",
        "pydantic>=2.0.0",
    ],
    entry_points={
        "console_scripts": [
            "apx=bridge.cli:main",
            "bridge=bridge.cli:main",
        ],
    },
)
