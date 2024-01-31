# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

DEPS = [
    'recipe_engine/properties',
    'cros_relevance',
    'gerrit',
]



def RunSteps(api):
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)

  # TODO (crbug/1111319): Add assertions once crrev.com/c/2347449 and
  # crrev.com/c/2347393 land, add assertions
  api.cros_relevance.get_package_dependencies(sysroot, Chroot(),
                                              api.properties['patch_sets'])


def GenTests(api):

  yield api.test('no-changes', api.properties(patch_sets=[]))

  yield api.test('with-changes',
                 api.properties(patch_sets=[api.gerrit.test_patch_set()]))
