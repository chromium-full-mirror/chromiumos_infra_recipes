# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Records per-target firmware configs in Cloud Spanner."""

from .api import FirmwareConfigApi as API

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/raw_io',
    'recipe_engine/service_account',
    'recipe_engine/step',
    'cros_infra_config',
    'cros_version',
    'src_state',
]
