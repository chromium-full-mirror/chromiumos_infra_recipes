# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  with api.cros_sdk.cleanup_context(checkout_path=api.src_state.workspace_path):
    with api.assertions.assertRaises(StepFailure), api.cros_sdk.snapshot():
      pass  # pragma: nocover


def GenTests(api):
  yield api.test(
      'basic',
      api.cros_build_api.remove_endpoints([
          'SdkService/CreateSnapshot',
      ]))
