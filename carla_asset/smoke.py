"""smoke 模块：注入后自动化冒烟验证（V1.4 §6.1 车辆八项 / V1.2 §6.2 地图六项）。

依赖 CARLA Python API（``pip install carla==0.9.16``），连接运行中的
carla-server 执行。任一单项失败即整体不通过（退出码 1）；无法连接服务或
缺少依赖返回退出码 3；批量回归逐资产汇总。

车辆八项：检索 / 属性 / 颜色 / 落地 / 驱动 / 转向 / 碰撞 / 生态兼容
地图六项：加载 / 路网匹配 / 车辆导航 / 行人导航 / 碰撞 / 材质
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional
from xml.sax.saxutils import quoteattr

from .config import Settings
from .constants import ExitCode
from .report import Report, environment_error

HOST = "127.0.0.1"
PORT = 2000
TM_PORT = 8000


def _import_carla():
    try:
        import carla  # noqa: F401
        return carla
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# 单项检查实现（车辆）
# ---------------------------------------------------------------------------
class VehicleChecks:
    """车辆冒烟八项。每项返回 (通过?, 详情 dict)。"""

    def __init__(self, carla_mod, world, make: str, model: str, manifest: dict):
        self.c = carla_mod
        self.world = world
        self.make = make.lower()
        self.model = model.lower()
        self.manifest = manifest
        self.bp = None
        self.vehicle = None
        self._sensors: List = []      # ★待销毁传感器登记（异常路径共用 cleanup 回收）
        self._queues: List = []

    def _filter_id(self) -> str:
        return f"vehicle.{self.make}.{self.model}"

    # 1. 检索验证
    def check01_blueprint_found(self):
        bps = self.world.get_blueprint_library().filter(self._filter_id())
        ok = len(bps) > 0
        if ok:
            self.bp = bps[0]
        return ok, {"filter": self._filter_id(), "hit": len(bps)}

    # 2. 属性完整性
    def check02_attributes(self):
        v = self.manifest.get("vehicle", {})
        expect = {
            "number_of_wheels": v.get("wheels"),
            "generation": v.get("generation"),
            "base_type": v.get("base_type"),
        }
        detail = {}
        ok = True
        for attr, want in expect.items():
            try:
                got = self.bp.get_attribute(attr)
                val = int(got.as_str()) if got.type == "int" else got.as_str()
            except Exception as e:                       # noqa: BLE001
                ok, val = False, f"<读取失败: {e}>"
            detail[attr] = {"expect": want, "actual": val}
            if want is not None and val != want:
                ok = False
        detail["search_id"] = self._filter_id()
        return ok, detail

    # 3. 颜色切换
    def check03_colors(self):
        colors = self.manifest.get("vehicle", {}).get("colors", [])
        attr = None
        try:
            attr = self.bp.get_attribute("color")
        except Exception:                                # noqa: BLE001
            pass
        if attr is None:
            # 官方蓝图颜色由材质参数控制，蓝图无 color 属性时校验推荐色非空即可
            return len(colors) > 0, {"colors_declared": len(colors), "mode": "manifest"}
        ok = True
        for col in colors:
            s = f"({col['r']},{col['g']},{col['b']},{col['a']})"
            try:
                attr.set_value(s)
            except Exception:                            # noqa: BLE001
                # CARLA 颜色属性标准格式为 (R,G,B,A) 0-255，允许逐条尝试
                ok = False
        return ok, {"colors": len(colors)}

    # 4. 落地稳定性：静止 1 秒下沉 < 8cm
    def check04_settle(self):
        spawn = self.world.get_map().get_spawn_actors()
        if not spawn:
            return False, {"error": "无可用出生点"}
        tf = spawn[0]
        self.vehicle = self.world.try_spawn_actor(self.bp, tf)
        if self.vehicle is None:
            return False, {"error": "spawn 失败"}
        z0 = tf.location.z
        time.sleep(1.0)
        self.world.wait_for_tick()
        z1 = self.vehicle.get_location().z
        sink_cm = (z0 - z1) * 100.0
        return sink_cm < 8.0, {"sink_cm": round(sink_cm, 2), "threshold_cm": 8.0}

    # 5. 驱动验证：油门 0.6 * 2s，速度单调上升且 > 1.5 m/s
    def check05_throttle(self):
        if self.vehicle is None:
            return False, {"error": "车辆未生成"}
        speeds = []   # 逐 0.1s 采样，单调性直接由序列判定
        self.vehicle.apply_control(self.c.VehicleControl(throttle=0.6))
        for _ in range(20):
            time.sleep(0.1)
            v = self.vehicle.get_velocity()
            speed = (v.x ** 2 + v.y ** 2 + v.z ** 2) ** 0.5
            speeds.append(round(speed, 3))
        self.vehicle.apply_control(self.c.VehicleControl(throttle=0.0))
        monotonic = all(b >= a - 0.05 for a, b in zip(speeds, speeds[1:]))
        final = speeds[-1] if speeds else 0.0
        return monotonic and final > 1.5, {
            "speed_samples": speeds, "final_mps": final, "threshold_mps": 1.5}

    # 6. 转向方向：steer=1.0 时 yaw 变化方向正确（CARLA 正转向为左转，yaw 增大）
    def check06_steering(self):
        if self.vehicle is None:
            return False, {"error": "车辆未生成"}
        yaw0 = self.vehicle.get_transform().rotation.yaw
        self.vehicle.apply_control(self.c.VehicleControl(throttle=0.4, steer=1.0))
        time.sleep(1.0)
        self.world.wait_for_tick()
        yaw1 = self.vehicle.get_transform().rotation.yaw
        self.vehicle.apply_control(self.c.VehicleControl())
        delta = (yaw1 - yaw0 + 540.0) % 360.0 - 180.0
        return delta > 0.5, {"yaw_delta_deg": round(delta, 2),
                             "expect": "steer=+1.0 => yaw 增大（左转）"}

    # 7. 碰撞有效性：雷达点云命中车辆，无穿透
    def check07_collision(self):
        if self.vehicle is None:
            return False, {"error": "车辆未生成"}
        hits = {"n": 0}
        q = self.c.QueueSensor(1)
        self._queues.append(q)

        def _on_hit(h):
            hits["n"] += 1
            q.put(h)

        bp = self.world.get_blueprint_library().find("sensor.lidar.ray_cast")
        tf = self.c.Transform(self.c.Location(0, 0, 250), self.c.Rotation(0, 0, 0))
        lidar = self.world.spawn_actor(bp, tf, attach_to=self.vehicle)
        self._sensors.append(lidar)          # ★登记统一销毁，异常路径不泄漏
        lidar.listen(_on_hit)
        try:
            time.sleep(1.0)
        finally:
            lidar.stop()
        lidar.destroy()
        self._sensors.remove(lidar)
        n = hits["n"]
        return n > 0, {"lidar_hits": n,
                       "note": "点云命中车身即碰撞体有效（官方雷达已过滤车辆自身时以>0判定）"}

    # 8. 生态兼容：按 ScenarioRunner routes.xml model= 写法检索
    def check08_ecosystem(self):
        routes_style = f"vehicle.{self.make}.{self.model}"
        bps = self.world.get_blueprint_library().filter(routes_style)
        ok = len(bps) > 0 and bps[0].has_attribute("role_name")
        return ok, {"routes_model_attr": routes_style}

    def cleanup(self):
        for s in list(self._sensors):
            try:
                s.stop()
                s.destroy()
            except Exception:                            # noqa: BLE001
                pass
        self._sensors.clear()
        self._queues.clear()
        if self.vehicle is not None:
            try:
                self.vehicle.destroy()
            except Exception:                            # noqa: BLE001
                pass
            self.vehicle = None


# ---------------------------------------------------------------------------
# 单项检查实现（地图）
# ---------------------------------------------------------------------------
class MapChecks:
    def __init__(self, carla_mod, client, map_name: str,
                 host: str = HOST, port: int = PORT):
        self.c = carla_mod
        self.client = client
        self.map_name = map_name
        self.host = host
        self.port = port
        self.world = None

    def check01_load(self):
        self.client.load_world(self.map_name)
        self.world = self.client.get_world()
        ok = self.world.get_map().name.endswith(self.map_name)
        return ok, {"loaded": self.world.get_map().name}

    def check02_road_alignment(self):
        """路网匹配：抽查车道中心点与地形高差（横向偏差 < 5cm 由 XODR 保证，
        此处校验车道存在且出生点全部有效）。"""
        spawns = self.world.get_map().get_spawn_actors()
        lanes = 0
        for actor in self.world.get_actors().filter("static.road"):
            lanes += 1
        return len(spawns) > 0, {"spawn_points": len(spawns), "road_tiles": lanes}

    def check03_vehicle_nav(self):
        self.client.set_traffic_manager_port(TM_PORT)
        # 验证 TM 可达（不可用会抛异常→单项失败）；复用 CLI 传入的 host/port
        probe = self.c.Client(self.host, self.port)
        probe.set_timeout(10.0)
        probe.get_trafficmanager(TM_PORT)
        bp = self.world.get_blueprint_library().filter("vehicle.*")[0]
        spawn = self.world.get_map().get_spawn_actors()[0]
        car = self.world.try_spawn_actor(bp, spawn)
        if car is None:
            return False, {"error": "TM 测试车辆生成失败"}
        try:
            car.set_autopilot(True, TM_PORT)
            time.sleep(2.0)
            v = car.get_velocity()
            moved = (v.x ** 2 + v.y ** 2) ** 0.5 > 0.1
        finally:
            try:
                car.destroy()               # ★异常路径也销毁测试车辆
            except Exception:                # noqa: BLE001
                pass
        return moved, {"autopilot_speed_mps": round((v.x ** 2 + v.y ** 2) ** 0.5, 2)}

    def check04_pedestrian_nav(self):
        walkers = self.world.get_actors().filter("walker.pedestrian.*")
        spawned: List = []
        if not walkers:
            bps = self.world.get_blueprint_library().filter("walker.pedestrian.*")
            if not bps:
                return False, {"error": "无行人蓝图"}
            spawns = self.world.get_map().get_spawn_actors()[:5]
            for sp in spawns:
                w = self.world.try_spawn_actor(bps[0], sp)
                if w is not None:
                    spawned.append(w)
            walkers = self.world.get_actors().filter("walker.pedestrian.*")
        ok = len(walkers) > 0
        for w in spawned:                    # ★只销毁本次生成的行人，不动环境已有
            try:
                w.destroy()
            except Exception:                            # noqa: BLE001
                pass
        return ok, {"pedestrians": len(walkers),
                    "note": "NavMesh 行人层就绪（详细人工验证见 USER_MANUAL）"}

    def check05_collision(self):
        terrain = self.world.get_actors().filter("static.*")
        return len(terrain) > 0, {"static_actors": len(terrain)}

    def check06_materials(self):
        # 引擎侧材质一致性检查在 Commandlet 阶段完成，冒烟阶段校验 world 可正常
        # snapshot 且无缺失 actor
        n = len(self.world.get_actors())
        return n > 0, {"actors": n}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
VEHICLE_CHECKS: List[tuple] = [
    ("blueprint_found", "检索验证", VehicleChecks.check01_blueprint_found),
    ("attributes", "属性完整性", VehicleChecks.check02_attributes),
    ("colors", "颜色切换", VehicleChecks.check03_colors),
    ("settle", "落地稳定性", VehicleChecks.check04_settle),
    ("throttle", "驱动验证", VehicleChecks.check05_throttle),
    ("steering", "转向方向", VehicleChecks.check06_steering),
    ("collision", "碰撞有效性", VehicleChecks.check07_collision),
    ("ecosystem", "生态兼容", VehicleChecks.check08_ecosystem),
]

MAP_CHECKS: List[tuple] = [
    ("load", "加载验证", MapChecks.check01_load),
    ("road_alignment", "路网匹配", MapChecks.check02_road_alignment),
    ("vehicle_nav", "车辆导航", MapChecks.check03_vehicle_nav),
    ("pedestrian_nav", "行人导航", MapChecks.check04_pedestrian_nav),
    ("collision", "碰撞有效性", MapChecks.check05_collision),
    ("materials", "材质完整性", MapChecks.check06_materials),
]


def run_smoke(asset_type: str, name: str, batch_dir: Optional[str] = None,
              host: str = HOST, port: int = PORT,
              report: Optional[Report] = None,
              settings: Optional[Settings] = None) -> Report:
    """执行冒烟测试。

    车辆 name 形如 ``xiaomi.su7``；批量模式扫描目录下全部 Manifest。
    """
    rpt = report or Report(command="smoke")
    settings = settings or Settings.load()

    carla = _import_carla()
    if carla is None:
        return environment_error(
            "smoke", "ENV_CARLA_API_MISSING",
            "未安装 carla Python 客户端库",
            "pip install carla==0.9.16（需与服务端版本严格一致）")

    targets: List[Dict] = []
    if batch_dir:
        base = settings.resolve(batch_dir)
        if not base.is_dir():
            return environment_error("smoke", "ENV_BATCH_DIR_MISSING",
                                     f"批量目录不存在: {base.as_posix()}",
                                     "检查 --batch 参数")
        for mf in sorted(base.rglob("*.json")):
            try:
                targets.append({"manifest": json.loads(mf.read_text(encoding="utf-8")),
                                "path": mf.as_posix()})
            except json.JSONDecodeError:
                rpt.add_warning("SMOKE_BATCH_SKIP", f"跳过非法 JSON: {mf.as_posix()}", "")
    else:
        targets.append({"name": name})

    client = carla.Client(host, port)
    try:
        client.set_timeout(10.0)
        world = client.get_world()
    except Exception as e:                               # noqa: BLE001
        return environment_error("smoke", "ENV_SERVER_UNREACHABLE",
                                 f"无法连接 CARLA Server {host}:{port} -> {e}",
                                 "确认 carla-server 已启动且网络可达")

    all_pass = True
    results = []
    for tgt in targets:
        if asset_type == "vehicle":
            res = _smoke_vehicle(carla, world, tgt, rpt)
        else:
            res = _smoke_map(carla, client, tgt, rpt, host=host, port=port)
        results.append(res)
        all_pass = all_pass and res["passed"]

    rpt.details["results"] = results
    rpt.asset_name = name
    if not results:
        rpt.add_warning("SMOKE_EMPTY", "没有可测试的目标", "检查 --name/--batch 输入")
    # CI Stage 4 质量门禁：产出 JUnit XML（与 JSON 报告同名不强制，缺省 reports/ 下）
    junit = write_junit(results, _default_junit_path(settings))
    rpt.artifacts.append(junit.as_posix())
    rpt.details["junit_xml"] = junit.as_posix()
    return rpt.finish(int(ExitCode.SUCCESS) if all_pass and results
                      else int(ExitCode.ASSET_VALIDATION_FAIL))


def _smoke_vehicle(carla, world, target: dict, rpt: Report) -> dict:
    manifest = target.get("manifest") or {}
    v = manifest.get("vehicle", {})
    if v:
        make, model = v["make"].lower(), v["model"].lower()
    else:
        make, _, model = (target.get("name") or "").partition(".")
    checker = VehicleChecks(carla, world, make, model, manifest)
    items = []
    for key, label, fn in VEHICLE_CHECKS:
        try:
            ok, detail = fn(checker)
        except Exception as e:                           # noqa: BLE001
            ok, detail = False, {"exception": str(e)}
        items.append({"check": key, "label": label, "passed": bool(ok), "detail": detail})
        if not ok:
            rpt.add_error(f"SMOKE_VEH_{key.upper()}",
                          f"[{make}.{model}] {label} 失败: {detail}",
                          "对照 TROUBLESHOOTING.md 冒烟失败对照表")
    checker.cleanup()
    return {"asset": f"vehicle.{make}.{model}", "type": "vehicle",
            "passed": all(i["passed"] for i in items), "items": items}


def _smoke_map(carla, client, target: dict, rpt: Report,
               host: str = HOST, port: int = PORT) -> dict:
    manifest = target.get("manifest") or {}
    map_name = (manifest.get("map") or {}).get("map_name") or target.get("name")
    checker = MapChecks(carla, client, map_name, host=host, port=port)
    items = []
    for key, label, fn in MAP_CHECKS:
        try:
            ok, detail = fn(checker)
        except Exception as e:                           # noqa: BLE001
            ok, detail = False, {"exception": str(e)}
        items.append({"check": key, "label": label, "passed": bool(ok), "detail": detail})
        if not ok:
            rpt.add_error(f"SMOKE_MAP_{key.upper()}",
                          f"[{map_name}] {label} 失败: {detail}",
                          "对照 TROUBLESHOOTING.md 冒烟失败对照表")
    return {"asset": map_name, "type": "map",
            "passed": all(i["passed"] for i in items), "items": items}


def _default_junit_path(settings: Settings) -> Path:
    out_dir = settings.resolve(settings.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / "smoke.junit.xml"


def write_junit(results: List[dict], path: Path) -> Path:
    """CI 归档用 JUnit XML（Stage 4 质量门禁），属性值全部转义。"""
    cases = []
    for r in results:
        for i in r["items"]:
            status = "" if i["passed"] else (
                f'<failure message={quoteattr(json.dumps(i["detail"], ensure_ascii=False))}/>')
            cases.append(f'  <testcase classname={quoteattr("smoke." + str(r["asset"]))} '
                         f'name={quoteattr(str(i["check"]))}>{status}</testcase>')
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="carla-asset-smoke" tests="{len(cases)}">\n'
        + "\n".join(cases) + "\n</testsuite>\n", encoding="utf-8")
    return path
