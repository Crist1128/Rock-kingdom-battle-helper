"""rocom 当前 BWIKI 页面结构解析测试。"""

import pytest
from bs4 import BeautifulSoup

from app.data_pipeline.rocom import scraper


def test_parse_current_sprite_detail_layout() -> None:
    """当前精灵详情页结构应解析出六维、技能和克制关系。"""
    soup = BeautifulSoup(
        """
        <div class="sprite-phone-type">
          <span class="sprite_type" title="克制：幽、恶
被克制：幽、草
抵抗：幻、恶
被抵抗：冰、草">
            <img alt="图标 宠物 属性 光.png" />光
          </span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>生命</span><span>:</span></span>
          <span class="sprite-info-attrnum">120</span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>物攻</span><span>:</span></span>
          <span class="sprite-info-attrnum">80</span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>魔攻</span><span>:</span></span>
          <span class="sprite-info-attrnum">80</span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>物防</span><span>:</span></span>
          <span class="sprite-info-attrnum">105</span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>魔防</span><span>:</span></span>
          <span class="sprite-info-attrnum">105</span>
        </div>
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname"><span>速度</span><span>:</span></span>
          <span class="sprite-info-attrnum">92</span>
        </div>
        <div class="skill-single" data-param1="默认" data-param2="物攻" data-param3="普通">
          <div class="skill-single-head">
            <img alt="Skill 700001.png" />
            <span class="skill-name">猛烈撞击</span>
            <div class="skill-head-typelist">
              <span>耗能</span><span>分类</span><span>系别</span><span>威力</span>
              <span><img alt="图标 技能 星星背景.png" /><span>1</span></span>
              <span><img alt="图标 技能 类别 物攻.png" /></span>
              <span><img alt="图标 宠物 属性 普通.png" /></span>
              <span>65</span>
            </div>
          </div>
          <div class="skill-single-body">
            <div class="skill-desc">
              <div class="skill-desc-atk">对敌方精灵造成物理伤害。</div>
              <div class="skill-desc-story">头比计划先达到目的地。</div>
            </div>
            <div class="skill-source">解锁：（默认）Lv.1</div>
          </div>
        </div>
        """,
        "html.parser",
    )

    assert scraper.parse_attributes_from_detail(soup) == ["光"]
    assert scraper.parse_stat_block(soup) == {
        "hp": 120,
        "atk": 80,
        "sp_atk": 80,
        "def": 105,
        "sp_def": 105,
        "spd": 92,
        "total": 582,
    }
    assert scraper.parse_type_matchup(soup) == {
        "strong_against": ["幽", "恶"],
        "weak_to": ["幽", "草"],
        "resists": ["幻", "恶"],
        "resisted_by": ["冰", "草"],
    }

    skill = scraper.parse_skills(soup)[0]
    assert skill["name"] == "猛烈撞击"
    assert skill["attribute"] == "普通"
    assert skill["category"] == "物攻"
    assert skill["power"] == 65
    assert skill["cost"] == 1
    assert skill["level"] == 1
    assert skill["unlock_method"] == "默认"


def test_extract_sprite_image_prefers_current_all_image_tab() -> None:
    """当前页面应优先从全部图片页签提取真实本体立绘，而不是旧占位图。"""
    soup = BeautifulSoup(
        """
        <div class="rocom_sprite_grament_img">
          <img alt="页面 宠物 立绘 喵喵 1.png"
               src="https://patchwiki.biligame.com/images/rocom/placeholder.png" />
        </div>
        <div class="d-tab allImgTab">
          <div class="tab-content active">
            <img class="imgAll-sprite-img"
                 alt="JL huoshen.png"
                 src="https://example.test/480px-main.png"
                 srcset="https://example.test/720px-main.png 1.5x,
                         https://example.test/960px-main.png 2x" />
          </div>
          <div class="tab-content hidden">
            <img class="imgAll-sprite-img imgAll-sprite-scale"
                 alt="Egg huohua.png"
                 src="https://patchwiki.biligame.com/images/rocom/egg.png" />
          </div>
        </div>
        """,
        "html.parser",
    )

    assert scraper.extract_sprite_image_url(soup).endswith("/960px-main.png")


def test_parse_current_skill_detail_card(monkeypatch) -> None:
    """技能详情页卡片应解析威力、耗能、属性和描述。"""
    soup = BeautifulSoup(
        """
        <h1>疾风涡轮</h1>
        <div class="sd-skill-card">
          <div class="sd-skill-icon"><img alt="Skill 715017.png" /></div>
          <div class="sd-card-name">疾风涡轮</div>
          <span class="sd-skill-type"><img alt="图标 宠物 属性 翼.png" /><span>翼</span></span>
          <span class="sd-skill-cat">攻击</span>
          <div class="sd-skill-desc">
            造成物伤，无法主动使用，在使用3次翼系技能后会自动使用此技能。
          </div>
          <div class="sd-skill-meta">
            <span><strong>100</strong><em>威力</em></span>
            <span><strong>0</strong><em>耗能</em></span>
          </div>
        </div>
        """,
        "html.parser",
    )
    monkeypatch.setattr(scraper, "fetch", lambda _url: soup)

    skill = scraper.parse_skill_detail({"name": "疾风涡轮", "url": "https://example.test"})

    assert skill["name"] == "疾风涡轮"
    assert skill["attribute"] == "翼"
    assert skill["category"] == "攻击"
    assert skill["power"] == 100
    assert skill["cost"] == 0
    assert skill["parse_status"] == "parsed"


def test_parse_skill_list_filters_upload_links(monkeypatch) -> None:
    """技能索引中混入的上传文件链接不应进入技能目录。"""
    soup = BeautifulSoup(
        """
        <div id="mw-content-text">
          <div class="divsort" data-param1="魔攻" data-param2="机械">
            <a href="/rocom/index.php?title=特殊:上传文件&wpDestFile=技能图标_铁蒺藜.png"
               title="文件:技能图标 铁蒺藜.png">文件:技能图标 铁蒺藜.png</a>
          </div>
          <div class="divsort" data-param1="魔攻" data-param2="机械">
            <a href="/rocom/铁蒺藜" title="铁蒺藜">铁蒺藜</a>
          </div>
        </div>
        """,
        "html.parser",
    )
    monkeypatch.setattr(scraper, "fetch", lambda _url: soup)

    entries = scraper.parse_skill_list_page()

    assert [entry["name"] for entry in entries] == ["铁蒺藜"]


def test_parse_sprite_detail_falls_back_to_base_page(monkeypatch) -> None:
    """形态详情页为空时，应尝试基础名称页面，避免输出空六维。"""
    empty_page = BeautifulSoup(
        "<div id='mw-content-text'><h1>板板壳（本来的样子）</h1></div>",
        "html.parser",
    )
    attrs = [
        ("生命", 67),
        ("物攻", 28),
        ("物防", 64),
        ("魔攻", 72),
        ("魔防", 81),
        ("速度", 45),
    ]
    stat_html = "\n".join(
        f"""
        <div class="sprite-info-attr">
          <span class="sprite-info-attrname">{name}</span>
          <span class="sprite-info-attrnum">{value}</span>
        </div>
        """
        for name, value in attrs
    )
    base_page = BeautifulSoup(
        f"""<div id="mw-content-text">{stat_html}</div>""",
        "html.parser",
    )

    def fake_fetch(url: str) -> BeautifulSoup:
        return base_page if url.endswith("%E6%9D%BF%E6%9D%BF%E5%A3%B3") else empty_page

    monkeypatch.setattr(scraper, "fetch", fake_fetch)

    detail = scraper.parse_sprite_detail(
        {
            "no": 12,
            "name": "板板壳",
            "form": "本来的样子",
            "url": "https://wiki.biligame.com/rocom/板板壳（本来的样子）",
            "has_shiny": False,
        }
    )

    assert detail["stats"]["hp"] == 67
    assert detail["detail_url_used"].endswith("%E6%9D%BF%E6%9D%BF%E5%A3%B3")


def test_parse_current_dex_card_list_layout(monkeypatch) -> None:
    """Current `.dex-pet-card` dex list should produce sprite entries with metadata."""
    soup = BeautifulSoup(
        """
        <div id="mw-content-text">
          <div class="dex-pet-card" data-main-form="true">
            <a href="/rocom/%E7%81%AB%E8%8A%B1" title="火花">
              <span class="dex-pet-no">NO.007</span>
              <span class="dex-pet-name">火花</span>
            </a>
            <span class="dex-pet-stage">初始</span>
            <span class="dex-pet-element">火</span>
            <span class="dex-pet-form-type">主形态</span>
            <span class="dex-pet-evolution-role">一阶</span>
          </div>
          <div class="dex-pet-card">
            <a href="/rocom/%E7%81%AB%E8%8A%B1%EF%BC%88%E5%BC%82%E8%89%B2%EF%BC%89">
              <span>NO.007</span>
              <span class="dex-pet-name">火花</span>
              <span class="dex-pet-form">异色</span>
            </a>
          </div>
        </div>
        """,
        "html.parser",
    )
    monkeypatch.setattr(scraper, "fetch", lambda _url: soup)

    entries = scraper.parse_list_page()

    assert len(entries) == 2
    assert entries[0]["no"] == 7
    assert entries[0]["name"] == "火花"
    assert entries[0]["dex_stage"] == "初始"
    assert entries[0]["dex_element"] == "火"
    assert entries[0]["dex_is_main_form"] is True
    assert entries[1]["form"] == "异色"


def test_scrape_rocom_sprites_reports_progress(monkeypatch, tmp_path) -> None:
    """The crawler should report progress for sprite, skill and complete stages."""
    monkeypatch.setattr(
        scraper,
        "parse_list_page",
        lambda: [
            {
                "no": 1,
                "name": "TestMon",
                "form": None,
                "url": "https://example.test/elf",
                "has_shiny": False,
            }
        ],
    )
    monkeypatch.setattr(
        scraper,
        "parse_sprite_detail",
        lambda entry, data_dir=None, force=False: {
            **entry,
            "attributes": ["normal"],
            "stats": {},
            "ability": {},
            "type_matchup": {},
            "evolution_chain": [],
            "skills": [],
        },
    )
    monkeypatch.setattr(
        scraper,
        "parse_skill_list_page",
        lambda: [{"name": "TestSkill", "url": "https://example.test/skill"}],
    )
    monkeypatch.setattr(
        scraper,
        "parse_skill_detail",
        lambda entry, data_dir=None, force=False: {
            **entry,
            "attribute": "normal",
            "category": "physical",
            "power": 40,
            "cost": 1,
            "description": "",
            "parse_status": "parsed",
        },
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scraper.random, "uniform", lambda _a, _b: 0)
    events: list[dict] = []

    scraper.scrape_rocom_sprites(
        output=tmp_path / "sprites_raw.json",
        delay=0,
        progress_callback=events.append,
    )

    stages = [event["stage"] for event in events]
    assert "fetch_sprite_list" in stages
    assert "scrape_sprites" in stages
    assert "fetch_skill_list" in stages
    assert "scrape_skills" in stages
    assert stages[-1] == "scrape_complete"


def test_scrape_rocom_sprites_can_use_prefiltered_entries(monkeypatch, tmp_path) -> None:
    """New-only sync can pass pre-filtered sprite entries without parsing the full list again."""
    monkeypatch.setattr(
        scraper,
        "parse_list_page",
        lambda: pytest.fail("parse_list_page should not be called when entries are provided"),
    )
    monkeypatch.setattr(
        scraper,
        "parse_sprite_detail",
        lambda entry, data_dir=None, force=False: {
            **entry,
            "attributes": ["normal"],
            "stats": {},
            "ability": {},
            "type_matchup": {},
            "evolution_chain": [],
            "skills": [],
        },
    )
    monkeypatch.setattr(scraper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(scraper.random, "uniform", lambda _a, _b: 0)

    result = scraper.scrape_rocom_sprites(
        output=tmp_path / "sprites_raw.json",
        delay=0,
        skip_skill_catalog=True,
        entries=[
            {
                "no": 99,
                "name": "OnlyNew",
                "form": None,
                "url": "https://example.test/only-new",
                "has_shiny": False,
            }
        ],
    )

    assert result["stats"]["entries"] == 1
    assert result["sprites"][0]["name"] == "OnlyNew"
