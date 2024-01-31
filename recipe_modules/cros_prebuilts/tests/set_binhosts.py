# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos.common import BuildTarget
from PB.chromite.api import binhost as binhost_pb

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_prebuilts',
]



def RunSteps(api):
  # Normal run
  api.cros_prebuilts.set_binhosts(
      binhosts=[(BuildTarget(name='amd64-generic'), 'gs://some-uri/')],
      private=False, key=binhost_pb.POSTSUBMIT_BINHOST)

  # Empty binhosts
  with api.assertions.assertRaises(api.step.StepFailure):
    api.cros_prebuilts.set_binhosts(binhosts=[], private=False,
                                    key=binhost_pb.POSTSUBMIT_BINHOST)


def GenTests(api):
  yield api.test('basic')
