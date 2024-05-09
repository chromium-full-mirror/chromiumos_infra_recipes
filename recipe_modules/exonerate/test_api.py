# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api

from PB.chromiumos.test_disablement import TestDisablement
from PB.chromiumos.test_disablement import TestDisablementCfg
from PB.chromiumos.test_disablement import ExcludeCfg
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import builder_common as builder_common_pb2


class ExonerateTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Exonerate module."""

  def fake_exoneration_configs(self):
    """Returns fake configs for unittesting."""
    betty_criteria = TestDisablement.FilterCriterion(key='build_target',
                                                     values=['betty'])
    build_target_name_criteria = TestDisablement.FilterCriterion(
        key='build_target', values=['build_target_name'])

    target_criteria = TestDisablement.FilterCriterion(key='build_target',
                                                      values=['target'])
    exonerations = [
        TestDisablement(name='test1', bug_ids=['123456']),
        TestDisablement(name='test2', bug_ids=['123456']),
        TestDisablement(name='test3', dut_criteria=[build_target_name_criteria],
                        bug_ids=['123456']),
        TestDisablement(name='test4', dut_criteria=[build_target_name_criteria],
                        bug_ids=['123456']),
        TestDisablement(name='test6', dut_criteria=[betty_criteria],
                        bug_ids=['123456']),
        TestDisablement(name='arc.Boot', dut_criteria=[betty_criteria],
                        bug_ids=['123456']),
        TestDisablement(name='camera.TakesGreatPhotos', bug_ids=['123456'],
                        dut_criteria=[target_criteria]),
    ]

    return TestDisablementCfg(disablements=exonerations)

  def fake_config_file_contents(self):
    return self.m.gitiles.make_encoded_file_from_bytes(
        self.fake_exoneration_configs().SerializeToString())

  def fake_excludes_configs(self):
    """Returns fake excludes config for unittesting."""
    exclude_tests = [ExcludeCfg.ExcludeTest(name='test2')]
    exclude_suites = [ExcludeCfg.ExcludeSuite(name='suite1')]
    return ExcludeCfg(exclude_tests=exclude_tests,
                      exclude_suites=exclude_suites)

  def fake_excludes_config(self):
    return self.m.gitiles.make_encoded_file_from_bytes(
        self.fake_excludes_configs().SerializeToString())

  def empty_config_file_contents(self):
    return self.m.gitiles.make_encoded_file_from_bytes(b'')
