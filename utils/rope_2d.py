import torch
import torch.nn as nn
from functools import partial
import torch.nn.functional as F
from typing import Optional, Tuple


def init_t_xy(end_x: int, end_y: int):
    t = torch.arange(end_x * end_y, dtype=torch.float32)
    t_x = (t % end_x).float()
    t_y = torch.div(t, end_x, rounding_mode="floor").float()
    return t_x, t_y


def compute_axial_cis(dim: int, end_x: int, end_y: int, theta: float = 100.0):
    freqs_x = 1.0 / (theta ** (torch.arange(0, dim, 4)[: (dim // 4)].float() / dim))
    freqs_y = 1.0 / (theta ** (torch.arange(0, dim, 4)[: (dim // 4)].float() / dim))

    t_x, t_y = init_t_xy(end_x, end_y)
    freqs_x = torch.outer(t_x, freqs_x)
    freqs_y = torch.outer(t_y, freqs_y)
    freqs_cis_x = torch.polar(torch.ones_like(freqs_x), freqs_x)
    freqs_cis_y = torch.polar(torch.ones_like(freqs_y), freqs_y)
    return torch.cat([freqs_cis_x, freqs_cis_y], dim=-1).cuda()


def precompute_1d_freqs_cis(dim: int, end: int, theta: float = 10000.0):
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: (dim // 2)].float() / dim))
    t = torch.arange(end, device=freqs.device, dtype=torch.float32)
    freqs = torch.outer(t, freqs)
    freqs_cis = torch.polar(torch.ones_like(freqs), freqs)  # complex64
    return freqs_cis.cuda()


def reshape_for_broadcast(freqs_cis: torch.Tensor, x: torch.Tensor):
    ndim = x.ndim
    assert 0 <= 1 < ndim
    if freqs_cis.shape == (x.shape[-2], x.shape[-1]):
        shape = [d if i >= ndim - 2 else 1 for i, d in enumerate(x.shape)]
    elif freqs_cis.shape == (x.shape[-3], x.shape[-2], x.shape[-1]):
        shape = [d if i >= ndim - 3 else 1 for i, d in enumerate(x.shape)]
    elif freqs_cis.shape == (x.shape[1], x.shape[-1]):
        shape = [d if i == 1 or i == ndim - 1 else 1 for i, d in enumerate(x.shape)]

    return freqs_cis.view(*shape)


def apply_rotary_emb(xq: torch.Tensor, xk: torch.Tensor, freqs_cis: torch.Tensor):
    # import ipdb; ipdb.set_trace()
    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))
    freqs_cis = reshape_for_broadcast(freqs_cis, xq_)
    xq_out = torch.view_as_real(xq_ * freqs_cis).flatten(3)
    xk_out = torch.view_as_real(xk_ * freqs_cis).flatten(3)

    return xq_out.type_as(xq).to(xq.device), xk_out.type_as(xk).to(xk.device)


def apply_2d_rotary_emb(xq: torch.Tensor, xk: torch.Tensor, freqs_cis: torch.Tensor):
    # import ipdb; ipdb.set_trace()
    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))
    freqs_cis = reshape_for_broadcast(freqs_cis, xq_)
    xq_out = torch.view_as_real(xq_ * freqs_cis).flatten(3)
    xk_out = torch.view_as_real(xk_ * freqs_cis).flatten(3)

    return xq_out.type_as(xq).to(xq.device), xk_out.type_as(xk).to(xk.device)


def apply_1d_rotary_emb(
    xq: torch.Tensor,
    xk: torch.Tensor,
    freqs_cis: torch.Tensor,
) -> Tuple[torch.Tensor, torch.Tensor]:
    xq_ = torch.view_as_complex(xq.float().reshape(*xq.shape[:-1], -1, 2))
    xk_ = torch.view_as_complex(xk.float().reshape(*xk.shape[:-1], -1, 2))
    freqs_cis = reshape_for_broadcast(freqs_cis, xq_)
    xq_out = torch.view_as_real(xq_ * freqs_cis).flatten(3)
    xk_out = torch.view_as_real(xk_ * freqs_cis).flatten(3)
    return xq_out.type_as(xq), xk_out.type_as(xk)


# B, N, C = x.shape
# qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
# q, k, v = qkv[0], qkv[1], qkv[2]

if __name__ == "__main__":
    dim = 512
    batch_size = 3
    head = 12
    scales = [1, 2, 3, 4, 5, 6, 8, 10, 13, 16]  ## 10 scales
    freqs_cis_my = [
        compute_axial_cis(dim=512, end_x=scale, end_y=scale, theta=100.0) for scale in scales
    ]  ## freq lists
    print("freq shapes, ", [freq.shape for freq in freqs_cis_my])
    q_B_scale2_d = torch.randn(
        [batch_size, head, sum([x**2 for x in scales]), dim]
    )  ## as q with multi head, same as qkv[0]
    k_B_scale2_d = torch.randn(
        [batch_size, head, sum([x**2 for x in scales]), dim]
    )  ## as k with multi head, same as qkv[1]
    print("q shape after qkv proj and view to multi head", q_B_scale2_d.shape)

    cumulative_sums = [0]
    for scale in scales:
        cumulative_sums.append(cumulative_sums[-1] + scale**2)  ## idx to choose scale segments

    # 检索 my_list 中的对应片段
    q_out_list = []
    k_out_list = []
    for idx in range(len(scales)):
        start = cumulative_sums[idx]
        end = cumulative_sums[idx + 1]
        q = q_B_scale2_d[:, :, start:end, :]
        k = k_B_scale2_d[:, :, start:end, :]
        q_out, k_out = apply_rotary_emb(q, k, freqs_cis=freqs_cis_my[idx])
        q_out_list.append(q_out)
        k_out_list.append(k_out)

    q_out = torch.cat(q_out_list, 2)
    k_out = torch.cat(k_out_list, 2)

    print("q shape after apply rope", q_out.shape)

    # attn = (q * self.scale) @ k.transpose(-2, -1)
    # attn = attn.softmax(dim=-1)
    # attn = self.attn_drop(attn)
