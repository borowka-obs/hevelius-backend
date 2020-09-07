# Setting up database

CREATE USER 'hevelius'@'192.0.2.1' IDENTIFIED BY 'password';
GRANT ALL on hevelius.* to 'hevelius'@'192.0.2.1';

