package vn.swoosh.store.members.theanh.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import vn.swoosh.store.StoreSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class ProductController {
    private final JdbcTemplate db;
    private final ObjectMapper json;

    public ProductController(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    @GetMapping("/products")
    Map<String, Object> products() {
        return Map.of("products", db.queryForList(productQuery() + " WHERE shoes.status='ACTIVE' ORDER BY shoes.shoe_name")
            .stream().map(row -> StoreSupport.productJson(json, row)).toList());
    }

    @GetMapping("/top-products")
    Map<String, Object> topProducts() {
        return Map.of("products", db.queryForList("""
            SELECT COALESCE(items.shoe_code_snapshot,shoes.shoe_code) AS id,
                   COALESCE(items.shoe_name_snapshot,shoes.shoe_name) AS name,
                   SUM(items.quantity) AS quantity,SUM(items.quantity*items.unit_price) AS revenue
            FROM order_items items
            JOIN orders ON orders.order_id=items.order_id
            JOIN shoe_variants variants ON variants.variant_id=items.variant_id
            JOIN running_shoes shoes ON shoes.shoe_id=variants.shoe_id
            WHERE UPPER(orders.order_status) IN ('CONFIRMED','SHIPPING','COMPLETED','DELIVERED')
            GROUP BY COALESCE(items.shoe_code_snapshot,shoes.shoe_code),
                     COALESCE(items.shoe_name_snapshot,shoes.shoe_name)
            ORDER BY quantity DESC,revenue DESC OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY
            """));
    }

    static String productQuery() {
        return """
            SELECT shoes.shoe_code AS id,shoes.shoe_name AS name,
                   CAST(COALESCE(shoes.sale_price,shoes.base_price)/1000 AS INT) AS price,
                   COALESCE((
                     SELECT SUM(stocks.stock_quantity)
                     FROM shoe_variants variants
                     JOIN inventory_stocks stocks ON stocks.variant_id=variants.variant_id
                     WHERE variants.shoe_id=shoes.shoe_id
                   ),0) AS stock,
                   CASE WHEN shoes.status='ACTIVE' THEN 1 ELSE 0 END AS active,
                   CAST('#e8e5df' AS NVARCHAR(20)) AS bg,
                   CAST('[[\"#ffffff\",\"#111111\",\"#cccccc\"]]' AS NVARCHAR(MAX)) AS colors
            FROM running_shoes shoes
            """;
    }

    @GetMapping("/size-chart")
    Map<String, Object> sizeChart() {
        return Map.of("sizes", List.of(
            Map.of("eu",38,"us","5.5","uk","5","cm",24),
            Map.of("eu",39,"us","6.5","uk","6","cm",24.5),
            Map.of("eu",40,"us","7","uk","6","cm",25),
            Map.of("eu",41,"us","8","uk","7","cm",26),
            Map.of("eu",42,"us","8.5","uk","7.5","cm",26.5),
            Map.of("eu",43,"us","9.5","uk","8.5","cm",27.5),
            Map.of("eu",44,"us","10","uk","9","cm",28),
            Map.of("eu",45,"us","11","uk","10","cm",29)));
    }
}
