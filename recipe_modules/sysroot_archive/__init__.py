# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SysrootArchive API init file."""

from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties

DEPS = [
    'cros_build_api',
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/led',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
]


PROPERTIES = SysrootArchiveApiProperties
