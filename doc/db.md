# Setting up database

Setting up a new database goes the usual way:

```sql
CREATE USER 'hevelius'@'192.0.2.1' IDENTIFIED BY 'password';
GRANT ALL on hevelius.* to 'hevelius'@'192.0.2.1';
```

Then run the following command to import iteleskop schema with Hevelius changes:
