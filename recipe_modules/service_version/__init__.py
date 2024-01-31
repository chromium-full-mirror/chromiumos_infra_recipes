# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.service_version.service_version import \
  ServiceVersionProperties

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/step',
]


PROPERTIES = ServiceVersionProperties
