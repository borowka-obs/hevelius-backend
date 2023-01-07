from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

long_description = 'Hevelius - a software that aims to help manage \
amateur astronomical observatory. In particular: \
- manage and process frames \
- control aqusition (telescopes, cameras, etc) \
'

setup(
    name ='hevelius',
    version ='0.0.3',
    author ='Tomek Mrugalski',
    author_email ='thomson@klub.com.pl',
    url ='https://github.com/tomaszmrugalski/hevelius-backend',
    description ='Hevelius, a management package for astronomical observatories',
    long_description = long_description,
    long_description_content_type ="text/markdown",
    license ='MIT',
    packages = find_packages(),
    scripts =['bin/hevelius'],
    classifiers =(
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ),
    keywords ='astronomy photo management',
    install_requires = requirements,
    zip_safe = False
)
