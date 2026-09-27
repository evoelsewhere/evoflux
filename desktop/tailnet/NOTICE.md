# Embedded tailnet helper

`evoflux-tailnet` links the open-source Tailscale `tsnet` package. Tailscale
source code is distributed under the BSD 3-Clause License. The corresponding
source and license are available at <https://github.com/tailscale/tailscale>.

EvoFlux does not bundle Tailscale account credentials or an auth key. The
embedded node is enrolled interactively by its owner and stores its machine
identity inside the EvoFlux state directory.
