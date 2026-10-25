# License texts

Plain texts of the licenses `relay license add` can write, from the SPDX
license-list-data repository (https://github.com/spdx/license-list-data),
folder `text/`, at the pinned release tag **v3.27.0**. Fetched once with curl
and kept byte-exact; relay never fetches them at run time.

The only change `relay license add` makes is to fill the `<year>` and the
holder placeholder (`<copyright holders>` or `<owner>`) in the texts that have
them (MIT, BSD-2-Clause, BSD-3-Clause). The other texts are written as they are.

To move to a newer tag, fetch the same files again from that tag and change
the tag above.
