import numpy as np
import math
from scipy.spatial.transform import Rotation


def radians_to_degrees(radians):
    degrees = radians * (180 / math.pi)
    return degrees


def get_meta_data(poses):
    poses = np.concatenate([poses[0:1], poses], axis=0)
    rel_pose = np.linalg.inv(poses[:-1]) @ poses[1:]
    # rel_pose=  np.concatenate([rel_pose], axis=0)
    xyzs = rel_pose[:, :3, 3]
    xys = xyzs[:, :2]
    rel_yaws = radians_to_degrees(
        Rotation.from_matrix(rel_pose[:, :3, :3]).as_euler("zyx", degrees=False)[:, 0]
    )[:, np.newaxis]

    # rel_poses_yaws=np.concatenate([xys,rel_yaws[:,None]],axis=1)

    return {
        "rel_poses": xys,
        "rel_yaws": rel_yaws,
        # 'rel_poses_xyz': xyzs,
        # 'rel_poses_yaws':rel_poses_yaws,
    }
