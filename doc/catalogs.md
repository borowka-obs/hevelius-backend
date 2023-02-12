# Catalogs

Hevelius comes with several astronomical catalogs. Their use is not mandatory.
You may live without them just fine, but you'll need to use RA/DEC coordinates
all the time.

Currently there are 4 catalogs available:

- NGC
- IC
- Messier
- Caldwell

They're stored in `catalogs/` directory and are in `.psql` format. To install
them, run your `psql -U hevelius` client and then use `\i catalogs/filename`
command. For example, to install Messier catalog:

```
$ psql -U hevelius
psql (14.6 (Ubuntu 14.6-0ubuntu0.22.04.1), server 12.7 (Ubuntu 12.7-0ubuntu0.20.10.1))
Type "help" for help.

hevelius=> \i catalogs/catalog-messier.psql
DELETE 110
DELETE 1
INSERT 0 1
COPY 110
hevelius=>
```
