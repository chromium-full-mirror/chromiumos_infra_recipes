# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The `siso` module provides the ability to interact with Siso."""

from PB.recipe_modules.chromeos.siso.siso import SisoProperties

from .api import SisoApi as API

DEPS = [
    'recipe_engine/step',
]

PROPERTIES = SisoProperties
