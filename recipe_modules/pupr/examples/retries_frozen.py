# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import collections

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet
from RECIPE_MODULES.chromeos.pupr.api import HASHTAG_FREEZE_RETRIES

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
    'pupr',
]



def RunSteps(api):
  change_info = {1: {'change_id': 1, 'hashtags': [HASHTAG_FREEZE_RETRIES]}}
  open_cls = [
      PatchSet(
          collections.defaultdict(str, {
              'change_number': k,
              'info': v,
              'revision_info': {},
          })) for k, v in change_info.items()
  ]
  api.assertions.assertTrue(api.pupr.retries_frozen(open_cls))


def GenTests(api):
  yield api.test('basic')
