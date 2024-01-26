# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the service_version module."""

from PB.recipe_modules.chromeos.service_version.service_version import \
  ServiceVersionProperties

DEPS = [
    'recipe_engine/step',
]


PROPERTIES = ServiceVersionProperties
