# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/path',
    'payloads'
]

def RunSteps(api):
  image_path = api.path['start_dir'].join('chroot', 'image_path','image.img')
  api.payloads.generate_full(image_path, 'name', 'kern.bin', 'root.bin')
  api.payloads.generate_delta(image_path, 'name')
  api.payloads.generate_stateful(image_path)

def GenTests(api):
  yield api.test('basic')
