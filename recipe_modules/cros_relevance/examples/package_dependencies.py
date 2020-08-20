# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/properties',
    'cros_relevance',
    'gerrit',
]

from recipe_engine.recipe_api import Property

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.common import Chroot

PROPERTIES = {'patch_sets': Property(default=[])}


def RunSteps(api, patch_sets):
  bt = BuildTarget(name='my_build_target')
  sysroot = Sysroot(path='/build/target', build_target=bt)

  # TODO (crbug/1111319): Add assertions once crrev.com/c/2347449 and
  # crrev.com/c/2347393 land, add assertions
  api.cros_relevance.get_package_dependencies(sysroot, Chroot(), patch_sets)


def GenTests(api):

  yield api.test('no-changes')

  yield api.test('with-changes',
                 api.properties(patch_sets=[api.gerrit.test_patch_set()]))
