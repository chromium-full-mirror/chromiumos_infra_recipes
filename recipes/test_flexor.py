# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for testing Flexor's functionality. Only intended for use with ChromeOS Flex."""

DEPS = [
    'recipe_engine/step',
]



def RunSteps(api):
  api.step('say hello', ['echo', 'hello'])


def GenTests(api):
  yield api.test(
      'production',
      api.post_check(lambda check, steps: check('say hello' in steps)))
