# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_lkgm',
    'cros_infra_config',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.cros_infra_config.configure_builder()
  api.cros_lkgm.cleanup_cls()


def GenTests(api):

  def test(name, *args, **kwargs):
    return api.test(
        name,
        api.properties(
            **{
                '$chromeos/cros_lkgm': {
                    'enable_lkgm': kwargs.pop('enable_lkgm', True),
                    'full_run': kwargs.pop('full_run', True),
                },
            }), *args, **kwargs)

  yield test('cleanup')
  yield test('cleanup-staging', full_run=False)
  yield test('disabled-lkgm', enable_lkgm=False)
