# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_test_api


class CrosStorageTestApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing the CrosStorage module."""

  TEST_GS_OUTPUT_TEXT = """gs://chromeos-releases/stable-channel/arkham/13310.53.0/ChromeOS-factory-R85-13310.53.0-arkham.zip
gs://chromeos-releases/stable-channel/arkham/13310.53.0/ChromeOS-recovery-R85-13310.53.0-arkham.instructions
gs://chromeos-releases/stable-channel/arkham/13310.53.0/ChromeOS-recovery-R85-13310.53.0-arkham.instructions.json
gs://chromeos-releases/stable-channel/arkham/13310.53.0/ChromeOS-recovery-R85-13310.53.0-arkham.tar.xz
gs://chromeos-releases/stable-channel/arkham/13310.53.0/ChromeOS-test-R85-13310.53.0-arkham.tar.xz
gs://chromeos-releases/stable-channel/arkham/13310.53.0/chromeos-hwqual-arkham-R85-13310.53.0.tar.bz2
gs://chromeos-releases/stable-channel/arkham/13310.53.0/chromeos_13310.53.0_arkham_recovery_stable-channel_mp.bin
gs://chromeos-releases/stable-channel/arkham/13310.53.0/chromeos_13310.53.0_arkham_recovery_stable-channel_mp.bin.br.zip
gs://chromeos-releases/stable-channel/arkham/13310.53.0/chromeos_13310.53.0_arkham_recovery_stable-channel_mp.bin.json
gs://chromeos-releases/stable-channel/arkham/13310.53.0/chromeos_13310.53.0_arkham_recovery_stable-channel_mp.bin.zip
gs://chromeos-releases/stable-channel/arkham/13310.53.0/debug-arkham.tgz
gs://chromeos-releases/stable-channel/arkham/13310.53.0/full_dev_part_KERN.bin.gz
gs://chromeos-releases/stable-channel/arkham/13310.53.0/full_dev_part_ROOT.bin.gz
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0-13310.53.0_arkham_stable-channel_delta_test.bin-gvtdgytbmvstb6dnye7i7geezqntodma
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0-13310.53.0_arkham_stable-channel_delta_test.bin-gvtdgytbmvstb6dnye7i7geezqntodma.json
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0-13310.53.0_arkham_stable-channel_delta_test.bin-gvtdgytbmvstb6dnye7i7geezqntodma.log
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_mp.bin-gvtdgytbmvstbos5tz3xd624cm7nksxj.signed
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_mp.bin-gvtdgytbmvstbos5tz3xd624cm7nksxj.signed.json
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_mp.bin-gvtdgytbmvstbos5tz3xd624cm7nksxj.signed.log
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_test.bin-gvtdgytbmvstbenviyn4ccm4l2zoph5z
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_test.bin-gvtdgytbmvstbenviyn4ccm4l2zoph5z.json
gs://chromeos-releases/stable-channel/arkham/13310.53.0/payloads/chromeos_13310.53.0_arkham_stable-channel_full_test.bin-gvtdgytbmvstbenviyn4ccm4l2zoph5z.log
gs://chromeos-releases/stable-channel/arkham/13310.53.0/stateful.tgz"""

  def normal_test_data(self, step_name='discover gs artifacts.gsutil list'):
    return self.step_data(
        step_name, stdout=self.m.raw_io.output_text(self.TEST_GS_OUTPUT_TEXT))
