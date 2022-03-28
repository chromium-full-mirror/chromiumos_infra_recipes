# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.cros_provenance.cros_provenance import \
      ProvenanceProperties

DEPS = [
    'infra/cloudkms',
    'infra/provenance',
    'recipe_engine/file',
    'recipe_engine/json',
    'recipe_engine/path',
    'recipe_engine/step',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ProvenanceProperties
