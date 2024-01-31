# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.artifacts import PrepareForBuildResponse
from PB.recipe_modules.chromeos.sysroot_util.tests.test import TestInputProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'cros_sdk',
    'sysroot_util',
]


PROPERTIES = TestInputProperties


def RunSteps(api, properties):
  name = properties.builder_name or 'benchmark-afdo-process'
  config = api.cros_infra_config.get_builder_config(name)

  chroot = api.cros_sdk.chroot if properties.with_chroot else None
  relevance = api.sysroot_util.update_for_artifact_build(
      chroot, config.artifacts,
      force_relevance=properties.force_build_relevance,
      test_data=properties.api_response)
  api.assertions.assertEqual(relevance, properties.expected_relevance)


def GenTests(api):
  for name, value in PrepareForBuildResponse.BuildRelevance.items():
    # Skip UNSPECIFIED.
    if not value:
      continue
    for with_chroot in (False, True):
      for force in (False, True):
        test_name = 'with%s-chroot_force=%s_%s' % ('' if with_chroot else 'out',
                                                   force, name.title())
        yield api.test(
            test_name,
            api.properties(
                with_chroot=with_chroot, force_build_relevance=force,
                api_response='{"build_relevance": "%s"}' % name,
                expected_relevance=PrepareForBuildResponse.NEEDED
                if force else value))
