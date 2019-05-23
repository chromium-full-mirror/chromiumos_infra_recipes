# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'git',
    'naming',
]

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.testplans.target_test_requirements_config import HwTestCfg


def RunSteps(api):
  build = build_pb2.Build(builder=build_pb2.BuilderID(
      project='foo', bucket='bar', builder='baz'))
  api.assertions.assertEqual(
      api.naming.get_build_title(build), 'foo.bar.baz')
  commit = api.git.Commit('abcdef', '''
title

...and then a longer description. Have you heard the tragedy of Darth
Plagueis the Wise?
  ''')
  api.assertions.assertEqual(api.naming.get_commit_title(commit), 'title')

def GenTests(api):
  yield api.test('basic')
