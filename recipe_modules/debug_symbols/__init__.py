# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for working with debug symbols."""

from PB.recipe_modules.chromeos.debug_symbols.debug_symbols import \
  DebugSymbolsProperties

DEPS = [
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_infra_config',
    'failures',
    'gobin',
]


PROPERTIES = DebugSymbolsProperties
