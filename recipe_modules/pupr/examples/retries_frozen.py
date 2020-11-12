# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gerrit',
    'pupr',
]

import collections


def RunSteps(api):
  change_info = {
      1: {
          "change_id": 1,
          "hashtags": [api.pupr.HASHTAG_FREEZE_RETRIES]
      }
  }
  open_cls = [
      api.gerrit.PatchSet(
          collections.defaultdict(str, {
              "change_number": k,
              "info": v
          })) for k, v in change_info.items()
  ]
  api.assertions.assertTrue(api.pupr.retries_frozen(open_cls))


def GenTests(api):
  yield api.test('basic')
