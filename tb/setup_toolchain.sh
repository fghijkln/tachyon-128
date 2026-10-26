#!/bin/bash
# Rootless toolchain bootstrap (Linux x86_64/aarch64): micromamba env "hdl" with Verilator + g++,
# Yosys as WebAssembly (yowasp-yosys).  Writes ~/env.sh; use with `source ~/env.sh`.
set -e
ARCH=$(uname -m); [ "$ARCH" = x86_64 ] && MM=linux-64 GXX=gxx_linux-64 || { MM=linux-aarch64; GXX=gxx_linux-aarch64; }
mkdir -p ~/bin
if [ ! -x ~/bin/micromamba ]; then
  curl -sL https://micro.mamba.pm/api/micromamba/$MM/latest -o /tmp/mm.tar.bz2
  python3 -c "import tarfile; tarfile.open('/tmp/mm.tar.bz2', 'r:bz2').extract('bin/micromamba', '$HOME')"
  chmod +x ~/bin/micromamba
fi
export MAMBA_ROOT_PREFIX=$HOME/mamba
[ -d $MAMBA_ROOT_PREFIX/envs/hdl ] || ~/bin/micromamba create -y -q -n hdl -c conda-forge verilator $GXX make
pip install --user -q yowasp-yosys
TRIPLE=$(ls $MAMBA_ROOT_PREFIX/envs/hdl/bin | grep -m1 -- '-conda-linux-gnu-g++$' | sed 's/-g++$//')
ln -sf $MAMBA_ROOT_PREFIX/envs/hdl/bin/$TRIPLE-g++ ~/bin/g++
ln -sf $MAMBA_ROOT_PREFIX/envs/hdl/bin/$TRIPLE-gcc ~/bin/gcc
cat > ~/env.sh <<EOF
export MAMBA_ROOT_PREFIX=\$HOME/mamba
export PATH=\$HOME/mamba/envs/hdl/bin:\$HOME/.local/bin:\$HOME/bin:\$PATH
export CXX=$TRIPLE-g++ CC=$TRIPLE-gcc
EOF
echo "toolchain ready: source ~/env.sh"
