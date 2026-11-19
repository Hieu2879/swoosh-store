package vn.swoosh.store;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
public final class StoreDatabase {
    private final JdbcTemplate jdbc;
    private volatile boolean initialized;

    public StoreDatabase(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public boolean initialized() {
        return initialized;
    }

    void initialize() {
        List.of(
            """
            IF OBJECT_ID('dbo.app_sessions','U') IS NULL
            CREATE TABLE dbo.app_sessions (
              token_hash CHAR(64) NOT NULL PRIMARY KEY,
              csrf_token VARCHAR(64) NOT NULL,
              user_id INT NULL REFERENCES dbo.users(user_id) ON DELETE CASCADE,
              expires_at BIGINT NOT NULL
            )
            """,
            """
            IF OBJECT_ID('dbo.app_activity_logs','U') IS NULL
            CREATE TABLE dbo.app_activity_logs (
              id BIGINT IDENTITY(1,1) PRIMARY KEY,
              actor NVARCHAR(100) NOT NULL,
              action NVARCHAR(100) NOT NULL,
              entity NVARCHAR(50) NOT NULL,
              entity_id NVARCHAR(100) NOT NULL DEFAULT '',
              created_at DATETIME2 NOT NULL,
              ip_address VARCHAR(64) NOT NULL
            )
            """,
            """
            IF OBJECT_ID('dbo.role_permissions','U') IS NULL
            CREATE TABLE dbo.role_permissions (
              role_id INT NOT NULL REFERENCES dbo.roles(role_id) ON DELETE CASCADE,
              permission_id INT NOT NULL REFERENCES dbo.permissions(permission_id) ON DELETE CASCADE,
              PRIMARY KEY(role_id,permission_id)
            )
            """,
            """
            IF COL_LENGTH('dbo.users','username') IS NULL
              ALTER TABLE dbo.users ADD username VARCHAR(40) NULL
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID('dbo.users') AND name='UX_users_username')
              CREATE UNIQUE INDEX UX_users_username ON dbo.users(username) WHERE username IS NOT NULL
            """,
            """
            IF OBJECT_ID('dbo.staff_profiles','U') IS NULL
            CREATE TABLE dbo.staff_profiles (
              user_id INT NOT NULL PRIMARY KEY REFERENCES dbo.users(user_id) ON DELETE CASCADE,
              address NVARCHAR(255) NOT NULL,
              citizen_id VARCHAR(12) NOT NULL UNIQUE,
              birth_date DATE NOT NULL
            )
            """,
            """
            IF COL_LENGTH('dbo.size_charts','size_uk') IS NULL
              ALTER TABLE dbo.size_charts ADD size_uk DECIMAL(3,1) NULL
            """,
            """
            IF COL_LENGTH('dbo.coupons','used_count') IS NULL
              ALTER TABLE dbo.coupons ADD used_count INT NOT NULL CONSTRAINT DF_coupons_used_count DEFAULT 0
            """,
            """
            IF COL_LENGTH('dbo.coupons','is_active') IS NULL
              ALTER TABLE dbo.coupons ADD is_active BIT NOT NULL CONSTRAINT DF_coupons_is_active DEFAULT 1
            """,
            "ALTER TABLE dbo.coupons ALTER COLUMN start_date DATETIME2 NULL",
            "ALTER TABLE dbo.coupons ALTER COLUMN end_date DATETIME2 NULL",
            """
            IF COL_LENGTH('dbo.orders','coupon_id') IS NULL
              ALTER TABLE dbo.orders ADD coupon_id INT NULL REFERENCES dbo.coupons(coupon_id)
            """,
            """
            IF COL_LENGTH('dbo.orders','note') IS NULL
              ALTER TABLE dbo.orders ADD note NVARCHAR(500) NOT NULL CONSTRAINT DF_orders_note DEFAULT ''
            """,
            """
            IF COL_LENGTH('dbo.orders','points_awarded') IS NULL
              ALTER TABLE dbo.orders ADD points_awarded INT NOT NULL CONSTRAINT DF_orders_points DEFAULT 0
            """,
            """
            IF COL_LENGTH('dbo.orders','updated_at') IS NULL
              ALTER TABLE dbo.orders ADD updated_at DATETIME2 NULL
            """,
            "UPDATE dbo.orders SET updated_at=created_at WHERE updated_at IS NULL",
            """
            IF COL_LENGTH('dbo.order_items','shoe_code_snapshot') IS NULL
              ALTER TABLE dbo.order_items ADD shoe_code_snapshot VARCHAR(50) NULL
            """,
            """
            IF COL_LENGTH('dbo.order_items','shoe_name_snapshot') IS NULL
              ALTER TABLE dbo.order_items ADD shoe_name_snapshot NVARCHAR(200) NULL
            """,
            """
            IF COL_LENGTH('dbo.order_items','size_eu_snapshot') IS NULL
              ALTER TABLE dbo.order_items ADD size_eu_snapshot DECIMAL(3,1) NULL
            """,
            """
            IF COL_LENGTH('dbo.order_items','color_name_snapshot') IS NULL
              ALTER TABLE dbo.order_items ADD color_name_snapshot NVARCHAR(50) NULL
            """,
            """
            IF OBJECT_ID('dbo.loyalty_tiers','U') IS NULL
            CREATE TABLE dbo.loyalty_tiers (
              tier_id INT IDENTITY(1,1) PRIMARY KEY,
              tier_name NVARCHAR(40) NOT NULL UNIQUE,
              min_points INT NOT NULL UNIQUE CHECK(min_points>=0),
              benefits NVARCHAR(200) NOT NULL DEFAULT ''
            )
            """,
            """
            IF OBJECT_ID('dbo.loyalty_accounts','U') IS NULL
            CREATE TABLE dbo.loyalty_accounts (
              user_id INT NOT NULL PRIMARY KEY REFERENCES dbo.users(user_id) ON DELETE CASCADE,
              points INT NOT NULL DEFAULT 0 CHECK(points>=0),
              created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
            """,
            """
            IF OBJECT_ID('dbo.media_files','U') IS NULL
            CREATE TABLE dbo.media_files (
              media_id INT IDENTITY(1,1) PRIMARY KEY,
              filename VARCHAR(100) NOT NULL UNIQUE,
              alt_text NVARCHAR(150) NOT NULL DEFAULT '',
              created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
            )
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.permissions WHERE permission_code='orders.read')
              INSERT INTO dbo.permissions(permission_code,permission_name,module) VALUES('orders.read',N'Xem đơn hàng','orders')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.permissions WHERE permission_code='orders.update')
              INSERT INTO dbo.permissions(permission_code,permission_name,module) VALUES('orders.update',N'Cập nhật đơn hàng','orders')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE role_code='ADMIN')
              INSERT INTO dbo.roles(role_code,role_name,description) VALUES('ADMIN',N'Quản trị viên',N'Toàn quyền quản trị cửa hàng')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE role_code='CONSULTANT')
              INSERT INTO dbo.roles(role_code,role_name,description) VALUES('CONSULTANT',N'Nhân viên tư vấn',N'Tư vấn khách hàng')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE role_code='WAREHOUSE_STAFF')
              INSERT INTO dbo.roles(role_code,role_name,description) VALUES('WAREHOUSE_STAFF',N'Nhân viên kho',N'Quản lý kho hàng')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE role_code='SALES_STAFF')
              INSERT INTO dbo.roles(role_code,role_name,description) VALUES('SALES_STAFF',N'Nhân viên bán hàng',N'Xem và cập nhật đơn hàng')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.roles WHERE role_code='CONTENT_STAFF')
              INSERT INTO dbo.roles(role_code,role_name,description) VALUES('CONTENT_STAFF',N'Nhân viên nội dung',N'Quản lý nội dung')
            """,
            """
            INSERT INTO dbo.role_permissions(role_id,permission_id)
            SELECT r.role_id,p.permission_id
            FROM dbo.roles r CROSS JOIN dbo.permissions p
            WHERE r.role_code='SALES_STAFF' AND p.permission_code IN ('orders.read','orders.update')
              AND NOT EXISTS (
                SELECT 1 FROM dbo.role_permissions existing
                WHERE existing.role_id=r.role_id AND existing.permission_id=p.permission_id
              )
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.loyalty_tiers WHERE tier_name=N'Đồng')
              INSERT INTO dbo.loyalty_tiers(tier_name,min_points,benefits) VALUES(N'Đồng',0,N'Tích điểm cho mỗi đơn hàng hoàn tất.')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.loyalty_tiers WHERE tier_name=N'Bạc')
              INSERT INTO dbo.loyalty_tiers(tier_name,min_points,benefits) VALUES(N'Bạc',500,N'Ưu đãi dành cho khách hàng thân thiết.')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.loyalty_tiers WHERE tier_name=N'Vàng')
              INSERT INTO dbo.loyalty_tiers(tier_name,min_points,benefits) VALUES(N'Vàng',1500,N'Ưu đãi đặc biệt dành cho thành viên Vàng.')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.brands WHERE brand_name=N'Swoosh')
              INSERT INTO dbo.brands(brand_name,country) VALUES(N'Swoosh',N'Việt Nam')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.shoe_colors WHERE color_name=N'Mặc định')
              INSERT INTO dbo.shoe_colors(color_name,hex_code) VALUES(N'Mặc định','#111111')
            """,
            """
            IF NOT EXISTS (SELECT 1 FROM dbo.warehouses WHERE warehouse_name=N'Kho chính')
              INSERT INTO dbo.warehouses(warehouse_name,address) VALUES(N'Kho chính',N'Kho mặc định')
            """,
            """
            INSERT INTO dbo.size_charts(size_eu,size_us,size_uk,size_cm)
            SELECT v.size_eu,v.size_us,v.size_uk,v.size_cm
            FROM (VALUES
              (38,5.5,5.0,24.0),(39,6.5,6.0,24.5),(40,7.0,6.0,25.0),(41,8.0,7.0,26.0),
              (42,8.5,7.5,26.5),(43,9.5,8.5,27.5),(44,10.0,9.0,28.0),(45,11.0,10.0,29.0)
            ) v(size_eu,size_us,size_uk,size_cm)
            WHERE NOT EXISTS (SELECT 1 FROM dbo.size_charts s WHERE s.size_eu=v.size_eu)
            """,
            """
            DECLARE @brand_id INT=(SELECT TOP (1) brand_id FROM dbo.brands WHERE brand_name=N'Swoosh');
            INSERT INTO dbo.running_shoes(
              shoe_code,shoe_name,brand_id,gender_target,base_price,weight_gram,midsole_thickness_mm,
              heel_to_toe_drop_mm,cushion_level,stability_level,is_beginner_friendly,status
            )
            SELECT v.shoe_code,v.shoe_name,@brand_id,N'Unisex',v.price,250,25,10,N'Medium',N'Neutral',1,N'ACTIVE'
            FROM (VALUES
              ('aj5',N'Air Jordan 5',210000),('aj1',N'Air Jordan 1 Low',149000),
              ('aj12',N'Air Jordan 12 Retro',189000),('dunk',N'Dunk Low',115000),
              ('af1',N'Air Force 1',125000)
            ) v(shoe_code,shoe_name,price)
            WHERE NOT EXISTS (SELECT 1 FROM dbo.running_shoes s WHERE s.shoe_code=v.shoe_code)
            """,
            """
            DECLARE @color_id INT=(SELECT TOP (1) color_id FROM dbo.shoe_colors WHERE color_name=N'Mặc định');
            INSERT INTO dbo.shoe_variants(shoe_id,color_id,size_id,width_option,sku,is_active)
            SELECT s.shoe_id,@color_id,z.size_id,N'Standard',
                   CONCAT(s.shoe_code,'-default-',CONVERT(VARCHAR(10),CONVERT(INT,z.size_eu))),1
            FROM dbo.running_shoes s CROSS JOIN dbo.size_charts z
            WHERE s.shoe_code IN ('aj5','aj1','aj12','dunk','af1')
              AND NOT EXISTS (
                SELECT 1 FROM dbo.shoe_variants v WHERE v.shoe_id=s.shoe_id AND v.size_id=z.size_id
              )
            """,
            """
            DECLARE @warehouse_id INT=(SELECT TOP (1) warehouse_id FROM dbo.warehouses WHERE warehouse_name=N'Kho chính');
            INSERT INTO dbo.inventory_stocks(warehouse_id,variant_id,stock_quantity,reserved_quantity,updated_at)
            SELECT @warehouse_id,v.variant_id,10,0,SYSUTCDATETIME()
            FROM dbo.shoe_variants v JOIN dbo.running_shoes s ON s.shoe_id=v.shoe_id
            WHERE s.shoe_code IN ('aj5','aj1','aj12','dunk','af1')
              AND NOT EXISTS (
                SELECT 1 FROM dbo.inventory_stocks i WHERE i.warehouse_id=@warehouse_id AND i.variant_id=v.variant_id
              )
            """,
            """
            IF OBJECT_ID('dbo.user_view_history','U') IS NULL
            CREATE TABLE dbo.user_view_history (
              view_id INT IDENTITY(1,1) PRIMARY KEY,
              user_id INT NOT NULL REFERENCES dbo.users(user_id) ON DELETE CASCADE,
              shoe_id INT NOT NULL REFERENCES dbo.running_shoes(shoe_id) ON DELETE CASCADE,
              viewed_at DATETIME2 NOT NULL DEFAULT GETDATE()
            )
            """,
            """
            IF OBJECT_ID('dbo.shipping_zones','U') IS NULL
            CREATE TABLE dbo.shipping_zones (
              zone_id INT IDENTITY(1,1) PRIMARY KEY,
              province NVARCHAR(100) NOT NULL UNIQUE,
              base_fee DECIMAL(18,2) NOT NULL,
              free_ship_threshold DECIMAL(18,2) NULL,
              is_active BIT NOT NULL DEFAULT 1
            )
            """,
            """
            IF OBJECT_ID('dbo.referrals','U') IS NULL
            CREATE TABLE dbo.referrals (
              referral_id INT IDENTITY(1,1) PRIMARY KEY,
              referrer_user_id INT NOT NULL REFERENCES dbo.users(user_id),
              referred_user_id INT NOT NULL UNIQUE REFERENCES dbo.users(user_id),
              reward_coupon_id INT NULL REFERENCES dbo.coupons(coupon_id),
              created_at DATETIME2 NOT NULL DEFAULT GETDATE()
            )
            """,
            """
            DELETE FROM dbo.app_sessions
            WHERE expires_at<=DATEDIFF_BIG(SECOND,CONVERT(DATETIME2,'1970-01-01'),SYSUTCDATETIME())
            """
        ).forEach(jdbc::execute);
        initialized = true;
        System.out.println("Swoosh database initialization completed.");
    }
}
