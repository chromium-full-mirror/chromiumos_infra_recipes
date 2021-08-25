# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/swarming',
    'build_menu',
    'easy',
    'test_util',
]

from PB.recipe_modules.chromeos.build_menu.tests.is_staging import (
    StagingProperties)

PROPERTIES = StagingProperties


def RunSteps(api, properties):
  kwargs = {}

  if properties.HasField('is_staging'):
    is_staging = properties.is_staging.value
  else:
    is_staging = None
  if properties.provide_is_staging:
    kwargs['is_staging'] = is_staging

  with api.build_menu.configure_builder(**kwargs):
    api.easy.set_properties_step(is_staging=str(api.build_menu.is_staging))
    if properties.expected_is_staging:
      api.assertions.assertTrue(api.build_menu.is_staging)
    else:
      api.assertions.assertFalse(api.build_menu.is_staging)


def GenTests(api):

  def test(name, provide=True, give=None, expect=False, **kwargs):
    kwargs.setdefault('cq', True)
    props = StagingProperties(expected_is_staging=expect,
                              provide_is_staging=provide)
    if give is not None:
      props.is_staging.value = give
    return api.test(
        name,
        api.test_util.test_child_build('amd64-generic', **kwargs).build,
        api.swarming.properties(
            bot_id='chromeos-ci-infra-us-central1-b-x16-0-nvcj'),
        api.properties(props))

  for bucket in 'staging', 'cq':
    for builder in "amd64-generic-cq", "staging-amd64-generic-cq":
      for which in 'NotPassed', None, False, True:
        name = '%s_%s-%s' % (bucket, builder, which)
        if which is None or which == 'NotPassed':
          expect = bucket == 'staging' or builder.startswith('staging-')
          provide = which is None
          give = None
        else:
          give = which
          expect = which
          provide = True
        yield test(name, bucket=bucket, builder=builder, give=give,
                   provide=provide, expect=expect)
