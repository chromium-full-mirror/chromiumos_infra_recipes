# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/step',
    'chrome',
]



def RunSteps(api):
  with api.step.nest('sync chrome'):
    cache_path = api.path.cleanup_dir / 'snapshot_chrome'
    with api.context(cwd=cache_path / 'src'):
      api.chrome.cache_sync(cache_path=cache_path)


def GenTests(api):

  yield api.test('basic')
