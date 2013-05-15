# This file belongs to Gyrid.
#
# Gyrid is a mobile device scanner.
# Copyright (C) 2013  Roel Huybrechts
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

#include <Python.h>

#include <errno.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <iwlib.h>
#include <linux/sockios.h>
#include <sys/ioctl.h>

static int skfd;

static PyObject *
get_mode (PyObject * self, PyObject * args)
{
  char *devname;
  struct iwreq wrq;
  int mode;

  if (!PyArg_ParseTuple(args, "s", &devname)) {
    return NULL;
  }

  if(iw_set_ext(skfd, devname, SIOCGIWMODE, &wrq) < 0)
  {
    PyErr_SetString(PyExc_IOError, "getting mode failed");
    return NULL;
  }
  if (wrq.u.mode < IW_NUM_OPER_MODE) {
      mode = wrq.u.mode;
  } else {
      mode = IW_NUM_OPER_MODE; //Unknown/bug
  }
  return Py_BuildValue("i", mode);
}

static PyObject *
set_mode (PyObject * self, PyObject * args)
{
  char *devname;
  int mode;
  struct iwreq wrq;

  if (!PyArg_ParseTuple(args, "si", &devname, &mode)) {
    return NULL;
  }

  strncpy(wrq.ifr_name, devname, IFNAMSIZ);
  wrq.u.mode = mode;

  if(iw_set_ext(skfd, devname, SIOCSIWMODE, &wrq) < 0)
  {
    PyErr_SetString(PyExc_IOError, "setting mode failed");
    return NULL;
  }
  Py_INCREF(Py_None);
  return Py_None;
}

static PyObject *
get_frequency (PyObject * self, PyObject * args)
{
  char *devname;
  struct iwreq wrq;

  if (!PyArg_ParseTuple(args, "s", &devname)) {
    return NULL;
  }

  if(iw_set_ext(skfd, devname, SIOCGIWFREQ, &wrq) < 0)
  {
    PyErr_SetString(PyExc_IOError, "getting frequency failed");
    return NULL;
  }
  return Py_BuildValue("f", iw_freq2float(&(wrq.u.freq))/1000000);
}

static PyObject *
set_frequency (PyObject * self, PyObject * args)
{
  char *devname;
  double freq;
  struct iwreq wrq;

  if (!PyArg_ParseTuple(args, "sd", &devname, &freq)) {
    return NULL;
  }

  freq = freq * 1000000;
  iw_float2freq(freq, &(wrq.u.freq));

  if(iw_set_ext(skfd, devname, SIOCSIWFREQ, &wrq) < 0)
  {
    PyErr_SetString(PyExc_IOError, "setting frequency failed");
    return NULL;
  }
  Py_INCREF(Py_None);
  return Py_None;
}

static PyObject *
set_status (PyObject * self, PyObject * args)
{
  char *devname;
  int up;
  struct ifreq ifr;

  if (!PyArg_ParseTuple(args, "si", &devname, &up)) {
      return NULL;
  }

  if (up < 0 || up > 1) {
    PyErr_SetString(PyExc_AttributeError, "status should be either 0 or 1 (down or up respectively)");
    return NULL;
  }

  strncpy(ifr.ifr_name, devname, IF_NAMESIZE);
  if(ioctl(skfd, SIOCGIFFLAGS, &ifr) < 0) {
    PyErr_SetString(PyExc_IOError, "setting status failed");
    return NULL;
  }

  if (up == 1) {
      ifr.ifr_flags |= IFF_UP;
  } else if (up == 0) {
      ifr.ifr_flags &= ~IFF_UP;
  }

  ioctl(skfd, SIOCSIFFLAGS, &ifr);
  ioctl(skfd, SIOCGIFFLAGS, &ifr);
  return Py_BuildValue("i", ifr.ifr_flags & IFF_UP);
}

static PyObject *
get_status (PyObject * self, PyObject * args)
{
  char *devname;
  struct ifreq ifr;

  if (!PyArg_ParseTuple(args, "s", &devname)) {
      return NULL;
  }

  strncpy(ifr.ifr_name, devname, IF_NAMESIZE);
  if(ioctl(skfd, SIOCGIFFLAGS, &ifr) < 0) {
    PyErr_SetString(PyExc_IOError, "getting status failed");
    return NULL;
  }
  return Py_BuildValue("i", ifr.ifr_flags & IFF_UP);
}

static struct PyMethodDef PyEthModuleMethods[] = {
        { "get_mode",
            (PyCFunction) get_mode, METH_VARARGS, NULL },
        { "set_mode",
            (PyCFunction) set_mode, METH_VARARGS, NULL },
        { "get_frequency",
            (PyCFunction) get_frequency, METH_VARARGS, NULL },
        { "set_frequency",
            (PyCFunction) set_frequency, METH_VARARGS, NULL },
        { "get_status",
            (PyCFunction) get_status, METH_VARARGS, NULL },
        { "set_status",
            (PyCFunction) set_status, METH_VARARGS, NULL },
	{ NULL, NULL, 0, NULL }
};

void initwigy(void) {
  PyObject *m, *d;

  m = Py_InitModule("wigy", PyEthModuleMethods);
  d = PyModule_GetDict(m);

  // Mapping WiFi modes to ID's and vice versa
  PyObject *id_mode = PyDict_New();
  PyObject *mode_id = PyDict_New();
  int i;
  for (i = 0; i < IW_NUM_OPER_MODE; i++) {
      PyDict_SetItem(id_mode, Py_BuildValue("i", i), Py_BuildValue("s", iw_operation_mode[i]));
      PyDict_SetItem(mode_id, Py_BuildValue("s", iw_operation_mode[i]), Py_BuildValue("i", i));
  }

  PyModule_AddObject(m, "ID_MODE", id_mode);
  PyModule_AddObject(m, "MODE_ID", mode_id);

  int eno;
  char buffer[1024];
  /* Create a channel to the NET kernel. */
  if((skfd = iw_sockets_open()) < 0) {
    eno = errno;
    sprintf(buffer, "iw_sockets_open [Errno %d] %s", eno, strerror(eno));
    PyErr_SetString(PyExc_IOError, buffer);
    return NULL;
  }
}
