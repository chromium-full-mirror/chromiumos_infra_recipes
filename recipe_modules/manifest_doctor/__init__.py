# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipe_modules.chromeos.manifest_doctor.manifest_doctor import ManifestDoctorProperties

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = ManifestDoctorProperties
