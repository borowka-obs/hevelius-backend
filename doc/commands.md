## Commands documentation

### Catalog - searching for catalog objects and associated frames

There are two ways how objects can be located. First is by using a name from the
catalog: `--object M1`. If the object is found, its coordinates are then used.
The alternative way is to specify the coordinates directly:
`--ra "11 22 33" --decl "-22 33 44"`. In both cases, you can specify the radius
around the specified object: `--proximity 2.0`. The default being 1 degree.

Hevelius will find catalog objects for you and also list frames that are in the
database. You can use `--format XXX` to specify the output format. See `--help`
for details as the formats are being updated frequently. As of time of writing
this text, the following formats were supported: `none`, `filenames`, `csv`,
`brief`, `full`, `pixinsight`.

The `pixinsight` format is intended to be used with PixInsight's
SubframeSelector. To import the list, open PixInsight, menu Process ->
ImageInspection -> SubframeSelector, then click on the `edit instance source code`
(square icon at the bottom), then paste the content into `P.subframes`.

An example command line call:

```python bin/hevelius catalog --object "C38 " --proximity 0.5 --format full```
