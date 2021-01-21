# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'cros_test_plan',
]


def RunSteps(api):
  test_plan = api.cros_test_plan.generate([Build()], [GerritChange()],
                                          GitilesCommit(id='1234abcd'))


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(project='chromeos', bucket='cq',
                               builder='lts-cq-orchestrator'))
