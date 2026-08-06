package demo;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {
    public Order save(Order order) {
        return order;
    }

    public Order findById(Long id) {
        return new Order();
    }
}
