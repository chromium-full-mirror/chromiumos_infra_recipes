# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Setup for the gcloud module."""

from PB.recipe_modules.chromeos.gcloud.gcloud import (GcloudProperties)

from .api import GcloudApi as API
from .test_api import GcloudApiTestApi as TEST_API

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'recipe_engine/swarming',
    'recipe_engine/time',
    'cros_infra_config',
    'easy',
    'overlayfs',
]


PROPERTIES = GcloudProperties
