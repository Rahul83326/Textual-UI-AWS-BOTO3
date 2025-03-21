from setuptools import setup, find_packages

setup(
    name="aws_status_app",
    version="1.0",
    packages=find_packages(),
    install_requires=[
        "boto3",
        "textual"
    ],
    entry_points={
        "console_scripts": [
            "aws-status=aws_status_app.server:main",  
        ]
    },
)