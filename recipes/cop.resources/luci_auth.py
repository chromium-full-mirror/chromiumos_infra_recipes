# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Luci auth helper functions"""

import subprocess


def get_token(minutes=5):
  """Returns an authentication token from luci-auth"""
  #Once infra-libs deps are compatible with google-cloud-build we can
  #remove this function with luci_auth.get_access_token()
  cmd = [
      'luci-auth', 'token', "-lifetime",
      "%dm" % minutes, "-scopes",
      "https://www.googleapis.com/auth/userinfo.email https://www.googleapis.com/auth/cloud-platform"
  ]
  return subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                 universal_newlines=True).rstrip()
