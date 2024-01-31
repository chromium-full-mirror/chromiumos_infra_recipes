# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2
from PB.chromiumos.common import PackageInfo

DEPS = [
    'recipe_engine/assertions',
    'git',
    'naming',
    'skylab_results',
]



def RunSteps(api):
  build = build_pb2.Build(
      builder=builder_common_pb2.BuilderID(project='foo', bucket='bar',
                                           builder='baz'))
  api.assertions.assertEqual(api.naming.get_build_title(build), 'baz')

  commit = api.git.Commit(
      'abcdef', '''
title

...and then a longer description. Have you heard the tragedy of Darth
Plagueis the Wise?
  ''')
  api.assertions.assertEqual(api.naming.get_commit_title(commit), 'title')

  hw_test = api.skylab_results.test_api.hw_test(name='hw-test')
  api.assertions.assertEqual(api.naming.get_hw_test_title(hw_test), 'hw-test')

  skylab_task = api.skylab_results.test_api.skylab_task(test=hw_test)
  api.assertions.assertEqual(
      api.naming.get_skylab_task_title(skylab_task), 'hw-test')

  skylab_result = api.skylab_results.test_api.skylab_result(task=skylab_task)
  api.assertions.assertEqual(
      api.naming.get_skylab_result_title(skylab_result), 'hw-test')
  api.assertions.assertEqual(
      api.naming.get_test_title(skylab_result), 'hw-test')

  properties = {'name': 'vm-test'}

  vm_test = build_pb2.Build()
  vm_test.input.properties.update(properties)
  api.assertions.assertEqual(api.naming.get_vm_test_title(vm_test), 'vm-test')

  vm_test = build_pb2.Build()
  vm_test.output.properties.update(properties)
  api.assertions.assertEqual(api.naming.get_vm_test_title(vm_test), 'vm-test')
  api.assertions.assertEqual(api.naming.get_test_title(vm_test), 'vm-test')

  package = PackageInfo(category='cat', package_name='name', version='123')
  api.assertions.assertEqual(
      api.naming.get_package_title(package), 'cat/name-123')


def GenTests(api):
  yield api.test('basic')
