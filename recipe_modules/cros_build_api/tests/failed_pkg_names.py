# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api import image
from PB.chromiumos import common as chromiumos

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_build_api',
]



def RunSteps(api):
  packages = [
      chromiumos.PackageInfo(package_name='p%d' % num) for num in range(60)
  ]
  # Test failed_pkg_names
  # We only care that the function gets used.
  input_proto = image.CreateImageRequest()
  api.cros_build_api.ImageService.Create(
      input_proto, response_lambda=api.cros_build_api.failed_pkg_names)

  failed_packages = api.cros_build_api.failed_pkg_names(
      image.CreateImageResult(failed_packages=packages))

  api.assertions.assertTrue('...' in failed_packages)


def GenTests(api):
  yield api.test('basic')
