# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating artifacts for Informational builders.

This recipe supports the workflow necessary to support asan, UBsan, and fuzzer
builder profiles."""

DEPS = [
    'build_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'


def RunSteps(api):
  with api.build_menu.configure_builder(), \
      api.build_menu.setup_workspace_and_chroot():
    return


def GenTests(api):

  def test(name, **kwargs):
    return api.test(name, api.test_util.test_child_build(None, **kwargs).build)

  yield test('basic', builder='amd64-generic-asan')
