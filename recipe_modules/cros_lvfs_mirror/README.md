# cros_lvfs_mirror Recipe

[TOC]

## Overview

This recipe contains the logic to sync an LVFS repository to our local
mirror in Google Storage. LVFS stands for Linux Vendor FileSystem and
contains a collection of firmware update files for many devices from
different vendors in the ecosystem. The sync recipe is powered by
[pulp](https://pulpproject.org/) and is implemented using a third
party script
[sync-pulp.py](https://github.com/fwupd/lvfs-website/blob/HEAD/contrib/sync-pulp.py).
